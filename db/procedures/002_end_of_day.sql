-- =============================================================================
-- FILE: db/procedures/002_end_of_day.sql
-- PROJECT: Paper-Trading Exchange — Group 9, CS F212 Database Systems
-- DESCRIPTION:
--   Stored procedure end_of_day(p_date DATE)
--   Runs the nightly batch settlement for a given trading date:
--     1. COUPON PAYMENTS   — pay periodic bond coupons to holders
--     2. OPTION EXPIRY     — compute intrinsic value and settle expiring options
--     3. INSTRUMENT EXPIRY — mark bonds and options as EXPIRED
-- PostgreSQL 16+   Run AFTER 001_schema.sql
-- =============================================================================

CREATE OR REPLACE PROCEDURE end_of_day(p_date DATE)
LANGUAGE plpgsql
AS $$
DECLARE
    -- Bond coupon loop
    v_bond              RECORD;
    v_holder            RECORD;
    v_coupon_amount     NUMERIC(20,6);
    v_ledger_id         BIGINT;

    -- Option settlement loop
    v_opt               RECORD;
    v_underlying_close  NUMERIC(20,6);
    v_intrinsic         NUMERIC(20,6);
    v_opt_holder        RECORD;
    v_payout            NUMERIC(20,6);
BEGIN
    -- =========================================================================
    -- PHASE 1: COUPON PAYMENTS
    --
    -- For every ACTIVE BOND instrument that has a coupon due on p_date,
    -- pay accounts currently holding that bond. Coupon due date logic:
    --   A coupon is due on p_date if the bond's coupon schedule falls on this date.
    --   Simplified rule: a coupon is due when EXTRACT(DAY FROM p_date) = 
    --   EXTRACT(DAY FROM bond.issue_date) on a period-aligned month.
    --   We use modular arithmetic on months elapsed since issue:
    --     months_elapsed % (12 / coupon_frequency) = 0
    --
    -- Idempotency: ON CONFLICT DO NOTHING on the UNIQUE(account_id, instrument_id,
    --   entry_type, value_date) constraint prevents double payments if run twice.
    -- =========================================================================

    FOR v_bond IN
        SELECT
            i.instrument_id,
            i.symbol,
            i.multiplier,
            b.face_value,
            b.coupon_rate,
            b.coupon_frequency,
            b.issue_date
        FROM bond b
        JOIN instrument i ON i.instrument_id = b.instrument_id
        WHERE i.status = 'ACTIVE'
          -- Coupon day: same day-of-month as issue_date AND
          -- the month count since issue is a multiple of (12/coupon_frequency)
          AND EXTRACT(DAY FROM p_date) = EXTRACT(DAY FROM b.issue_date)
          AND (
              (EXTRACT(YEAR FROM p_date)  - EXTRACT(YEAR FROM b.issue_date)) * 12
              + (EXTRACT(MONTH FROM p_date) - EXTRACT(MONTH FROM b.issue_date))
          )::INTEGER % (12 / b.coupon_frequency) = 0
          -- Don't pay on the issue date itself
          AND p_date > b.issue_date
    LOOP
        -- Coupon per unit = face_value × coupon_rate / coupon_frequency
        v_coupon_amount := v_bond.face_value
                           * v_bond.coupon_rate
                           / v_bond.coupon_frequency;

        FOR v_holder IN
            SELECT p.account_id, p.qty
            FROM position p
            WHERE p.instrument_id = v_bond.instrument_id
              AND p.qty > 0
        LOOP
            -- Total coupon payment = coupon_per_unit × qty × multiplier
            v_ledger_id := NULL;
            INSERT INTO cash_ledger (
                account_id,
                instrument_id,
                entry_type,
                amount,
                value_date
            )
            VALUES (
                v_holder.account_id,
                v_bond.instrument_id,
                'COUPON',
                v_coupon_amount * v_holder.qty * v_bond.multiplier,
                p_date
            )
            ON CONFLICT (account_id, instrument_id, entry_type, value_date)
            DO NOTHING    -- Idempotent: safe to re-run
            RETURNING ledger_id INTO v_ledger_id;

            -- Update account cash_balance only if the ledger row was actually inserted
            IF v_ledger_id IS NOT NULL THEN
                UPDATE account
                   SET cash_balance = cash_balance
                                    + (v_coupon_amount * v_holder.qty * v_bond.multiplier)
                 WHERE account_id = v_holder.account_id;
            END IF;

        END LOOP;
    END LOOP;


    -- =========================================================================
    -- PHASE 2: OPTION EXPIRY SETTLEMENT
    --
    -- For every ACTIVE OPTION expiring on or before p_date:
    --   • Find the latest PRICE_BAR close for the option's underlying instrument
    --   • Compute intrinsic value:
    --       CALL option: max(0, underlying_close − strike)
    --       PUT  option: max(0, strike − underlying_close)
    --   • For each holder with qty > 0: insert EXERCISE cash_ledger entry
    --     and update account.cash_balance; then zero out the position
    -- =========================================================================

    FOR v_opt IN
        SELECT
            i.instrument_id,
            i.symbol,
            i.multiplier,
            o.underlying_id,
            o.strike,
            o.expiry,
            o.option_type
        FROM option o
        JOIN instrument i ON i.instrument_id = o.instrument_id
        WHERE i.status   = 'ACTIVE'
          AND o.expiry  <= p_date
    LOOP
        -- Fetch the latest close price for the underlying
        SELECT pb.close
          INTO v_underlying_close
          FROM price_bar pb
         WHERE pb.instrument_id = v_opt.underlying_id
           AND pb.trade_date   <= p_date
         ORDER BY pb.trade_date DESC
         LIMIT 1;

        IF NOT FOUND THEN
            -- No price data — option expires worthless
            v_underlying_close := 0;
        END IF;

        -- Intrinsic value per unit
        IF v_opt.option_type = 'CALL' THEN
            v_intrinsic := GREATEST(0, v_underlying_close - v_opt.strike);
        ELSE
            v_intrinsic := GREATEST(0, v_opt.strike - v_underlying_close);
        END IF;

        FOR v_opt_holder IN
            SELECT p.account_id, p.qty
            FROM position p
            WHERE p.instrument_id = v_opt.instrument_id
              AND p.qty > 0
        LOOP
            v_payout := v_intrinsic * v_opt_holder.qty * v_opt.multiplier;

            IF v_intrinsic > 0 THEN
                -- Insert exercise ledger entry (idempotent)
                v_ledger_id := NULL;
                INSERT INTO cash_ledger (
                    account_id,
                    instrument_id,
                    entry_type,
                    amount,
                    value_date
                )
                VALUES (
                    v_opt_holder.account_id,
                    v_opt.instrument_id,
                    'EXERCISE',
                    v_payout,
                    p_date
                )
                ON CONFLICT (account_id, instrument_id, entry_type, value_date)
                DO NOTHING
                RETURNING ledger_id INTO v_ledger_id;

                -- Update cash_balance only if the row was freshly inserted
                IF v_ledger_id IS NOT NULL THEN
                    UPDATE account
                       SET cash_balance = cash_balance + v_payout
                     WHERE account_id = v_opt_holder.account_id;
                END IF;
            END IF;

            -- Zero out the position (option is gone regardless of intrinsic value)
            UPDATE position
               SET qty = 0
             WHERE account_id    = v_opt_holder.account_id
               AND instrument_id = v_opt.instrument_id;

        END LOOP;
    END LOOP;


    -- =========================================================================
    -- PHASE 3: EXPIRE INSTRUMENTS
    --
    -- Mark options (expiry <= p_date) and bonds (maturity_date <= p_date) as EXPIRED.
    -- Run AFTER phases 1 & 2 so the settlement logic above still sees ACTIVE status.
    -- =========================================================================

    UPDATE instrument
       SET status = 'EXPIRED'
     WHERE status <> 'EXPIRED'
       AND (
               (instrument_type = 'OPTION'
                AND instrument_id IN (
                    SELECT instrument_id FROM option WHERE expiry <= p_date
                ))
            OR
               (instrument_type = 'BOND'
                AND instrument_id IN (
                    SELECT instrument_id FROM bond WHERE maturity_date <= p_date
                ))
           );

    RAISE NOTICE 'end_of_day(%): all phases completed successfully.', p_date;

END;
$$;

COMMENT ON PROCEDURE end_of_day(DATE) IS
    'Nightly batch procedure for p_date:
     Phase 1 — pays periodic bond coupons to position holders (idempotent via UNIQUE constraint).
     Phase 2 — settles expiring options at intrinsic value, zeroes out positions.
     Phase 3 — marks expired options and matured bonds as EXPIRED in instrument table.
     Must be run once per trading day, ideally inside a BEGIN/COMMIT block.';

-- ===========================================================================
-- END OF end_of_day
-- ===========================================================================
