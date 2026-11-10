-- =============================================================================
-- FILE: db/procedures/001_match_and_settle.sql
-- PROJECT: Paper-Trading Exchange — Group 9, CS F212 Database Systems
-- DESCRIPTION:
--   Stored procedure match_and_settle(p_order_id BIGINT)
--   Implements the full order-matching engine (Workflow 1 from §2.1):
--     • Validates instrument status and account funds / position
--     • Loops to find the best resting counter-order (price-time priority)
--     • For each match: creates TRADE, ORDER_FILLs, updates POSITION,
--       inserts CASH_LEDGER entries, and updates ACCOUNT.Cash_balance
--     • Uses SERIALIZABLE isolation + SELECT ... FOR UPDATE row locking
-- PostgreSQL 16+   Run AFTER 001_schema.sql and 001_triggers.sql
-- =============================================================================

CREATE OR REPLACE PROCEDURE match_and_settle(p_order_id BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
    -- Incoming order
    v_incoming          trade_order%ROWTYPE;
    v_instrument        instrument%ROWTYPE;
    v_account           account%ROWTYPE;

    -- Resting order
    v_resting           trade_order%ROWTYPE;
    v_resting_account   account%ROWTYPE;

    -- Fill computation
    v_fill_qty          INTEGER;
    v_fill_price        NUMERIC(20,6);
    v_settlement_amount NUMERIC(20,6);
    v_remaining_inc     INTEGER;
    v_remaining_rest    INTEGER;

    -- Position tracking for buyer
    v_buyer_position    position%ROWTYPE;
    v_new_avg_cost      NUMERIC(20,6);

    -- Trade and fill sequence
    v_trade_id          BIGINT;
    v_buy_fill_seq      INTEGER;
    v_sell_fill_seq     INTEGER;

    -- Buyer / seller derived from order sides
    v_buy_order_id      BIGINT;
    v_sell_order_id     BIGINT;
    v_buyer_account_id  BIGINT;
    v_seller_account_id BIGINT;
BEGIN
    -- =========================================================================
    -- ISOLATION NOTE:
    --   The caller MUST invoke this procedure inside a SERIALIZABLE transaction:
    --     BEGIN ISOLATION LEVEL SERIALIZABLE;
    --     CALL match_and_settle(<order_id>);
    --     COMMIT;
    --   If the caller already set SERIALIZABLE before INSERTing the order,
    --   skip SET TRANSACTION (PostgreSQL rejects it once a snapshot is taken).
    -- =========================================================================
    IF current_setting('transaction_isolation') <> 'serializable' THEN
        SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
    END IF;

    -- =========================================================================
    -- STEP 1: Lock and fetch the incoming order
    -- =========================================================================
    SELECT * INTO v_incoming
      FROM trade_order
     WHERE order_id = p_order_id
       FOR UPDATE;             -- Row-level lock prevents concurrent fills

    IF NOT FOUND THEN
        RAISE EXCEPTION 'match_and_settle: order_id % not found.', p_order_id;
    END IF;

    IF v_incoming.status NOT IN ('OPEN', 'PARTIAL') THEN
        RAISE EXCEPTION
            'match_and_settle: order % has status % — only OPEN or PARTIAL orders can be matched.',
            p_order_id, v_incoming.status;
    END IF;

    -- =========================================================================
    -- STEP 2: Fetch and validate the instrument
    -- =========================================================================
    SELECT * INTO v_instrument
      FROM instrument
     WHERE instrument_id = v_incoming.instrument_id;

    IF v_instrument.status = 'EXPIRED' THEN
        RAISE EXCEPTION
            'match_and_settle: instrument % is EXPIRED — cannot match orders.',
            v_instrument.symbol;
    END IF;

    -- =========================================================================
    -- STEP 3: Lock the incoming order's account and validate funds / position
    -- =========================================================================
    SELECT * INTO v_account
      FROM account
     WHERE account_id = v_incoming.account_id
       FOR UPDATE;             -- Prevents concurrent balance modifications

    IF v_incoming.side = 'BUY' THEN
        -- Remaining cost = price × remaining_qty × multiplier
        v_remaining_inc := v_incoming.qty - v_incoming.filled_qty;
        IF v_account.cash_balance <
               (v_incoming.price * v_remaining_inc * v_instrument.multiplier) THEN
            RAISE EXCEPTION
                'match_and_settle: account % has insufficient cash (% available, % required) for BUY order %.',
                v_account.account_id,
                v_account.cash_balance,
                (v_incoming.price * v_remaining_inc * v_instrument.multiplier),
                p_order_id;
        END IF;
    ELSE
        -- SELL: validate the account has enough position
        v_remaining_inc := v_incoming.qty - v_incoming.filled_qty;
        PERFORM 1
          FROM position
         WHERE account_id    = v_incoming.account_id
           AND instrument_id = v_incoming.instrument_id
           AND qty           >= v_remaining_inc;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'match_and_settle: account % has insufficient position in instrument % to SELL % units.',
                v_incoming.account_id,
                v_instrument.symbol,
                v_remaining_inc;
        END IF;
    END IF;

    -- =========================================================================
    -- STEP 4: Matching loop
    -- =========================================================================
    LOOP
        v_remaining_inc := v_incoming.qty - v_incoming.filled_qty;

        EXIT WHEN v_remaining_inc <= 0;   -- Incoming order fully filled

        -- ------------------------------------------------------------------
        -- Find the best resting counter-order:
        --   • Incoming BUY  → find SELL at ask_price <= incoming bid_price
        --   • Incoming SELL → find BUY  at bid_price >= incoming ask_price
        -- Price-time priority: best price first (lowest ask / highest bid),
        -- then earliest created_at for ties.
        -- We lock it immediately to prevent another session from touching it.
        -- ------------------------------------------------------------------
        IF v_incoming.side = 'BUY' THEN
            SELECT * INTO v_resting
              FROM trade_order
             WHERE instrument_id = v_incoming.instrument_id
               AND side          = 'SELL'
               AND status        IN ('OPEN', 'PARTIAL')
               AND price         <= v_incoming.price
               AND order_id      <> v_incoming.order_id
             ORDER BY price ASC, created_at ASC
             LIMIT 1
               FOR UPDATE SKIP LOCKED;
        ELSE
            SELECT * INTO v_resting
              FROM trade_order
             WHERE instrument_id = v_incoming.instrument_id
               AND side          = 'BUY'
               AND status        IN ('OPEN', 'PARTIAL')
               AND price         >= v_incoming.price
               AND order_id      <> v_incoming.order_id
             ORDER BY price DESC, created_at ASC
             LIMIT 1
               FOR UPDATE SKIP LOCKED;
        END IF;

        -- No matching resting order — stop (incoming stays OPEN/PARTIAL)
        EXIT WHEN NOT FOUND;

        -- ------------------------------------------------------------------
        -- Lock the resting order's account
        -- ------------------------------------------------------------------
        SELECT * INTO v_resting_account
          FROM account
         WHERE account_id = v_resting.account_id
           FOR UPDATE;

        -- ------------------------------------------------------------------
        -- Compute fill quantity and price
        -- ------------------------------------------------------------------
        v_remaining_rest := v_resting.qty - v_resting.filled_qty;
        v_fill_qty       := LEAST(v_remaining_inc, v_remaining_rest);

        -- Price is the resting order's price (maker pricing)
        v_fill_price := v_resting.price;

        v_settlement_amount := v_fill_price * v_fill_qty * v_instrument.multiplier;

        -- Identify buy/sell accounts
        IF v_incoming.side = 'BUY' THEN
            v_buy_order_id      := v_incoming.order_id;
            v_sell_order_id     := v_resting.order_id;
            v_buyer_account_id  := v_incoming.account_id;
            v_seller_account_id := v_resting.account_id;
        ELSE
            v_buy_order_id      := v_resting.order_id;
            v_sell_order_id     := v_incoming.order_id;
            v_buyer_account_id  := v_resting.account_id;
            v_seller_account_id := v_incoming.account_id;
        END IF;

        -- ------------------------------------------------------------------
        -- INSERT TRADE
        -- ------------------------------------------------------------------
        INSERT INTO trade (buy_order_id, sell_order_id, price, qty, executed_at)
        VALUES (v_buy_order_id, v_sell_order_id, v_fill_price, v_fill_qty, NOW())
        RETURNING trade_id INTO v_trade_id;

        -- ------------------------------------------------------------------
        -- INSERT ORDER_FILLs (one per order leg)
        -- Fill_seq = next sequence number for each order
        -- ------------------------------------------------------------------

        -- Fill seq for the buy order
        SELECT COALESCE(MAX(fill_seq), 0) + 1
          INTO v_buy_fill_seq
          FROM order_fill
         WHERE order_id = v_buy_order_id;

        INSERT INTO order_fill (order_id, fill_seq, trade_id, qty, price, filled_at)
        VALUES (v_buy_order_id, v_buy_fill_seq, v_trade_id, v_fill_qty, v_fill_price, NOW());

        -- Fill seq for the sell order
        SELECT COALESCE(MAX(fill_seq), 0) + 1
          INTO v_sell_fill_seq
          FROM order_fill
         WHERE order_id = v_sell_order_id;

        INSERT INTO order_fill (order_id, fill_seq, trade_id, qty, price, filled_at)
        VALUES (v_sell_order_id, v_sell_fill_seq, v_trade_id, v_fill_qty, v_fill_price, NOW());

        -- Note: fn_fill_qty_sync trigger automatically updates filled_qty and status
        --       on trade_order after each order_fill INSERT above.

        -- ------------------------------------------------------------------
        -- UPDATE POSITION for buyer (upsert with weighted average cost)
        -- ------------------------------------------------------------------
        SELECT * INTO v_buyer_position
          FROM position
         WHERE account_id    = v_buyer_account_id
           AND instrument_id = v_incoming.instrument_id
           FOR UPDATE;

        IF FOUND THEN
            -- Weighted average cost: (old_qty × old_avg + fill_qty × fill_price) / new_qty
            v_new_avg_cost := (
                (v_buyer_position.qty * v_buyer_position.avg_cost)
                + (v_fill_qty * v_fill_price)
            ) / (v_buyer_position.qty + v_fill_qty);

            UPDATE position
               SET qty      = qty + v_fill_qty,
                   avg_cost = v_new_avg_cost
             WHERE account_id    = v_buyer_account_id
               AND instrument_id = v_incoming.instrument_id;
        ELSE
            INSERT INTO position (account_id, instrument_id, qty, avg_cost)
            VALUES (v_buyer_account_id, v_incoming.instrument_id, v_fill_qty, v_fill_price)
            ON CONFLICT (account_id, instrument_id) DO UPDATE
               SET qty      = position.qty + EXCLUDED.qty,
                   avg_cost = (
                       (position.qty * position.avg_cost + EXCLUDED.qty * EXCLUDED.avg_cost)
                       / (position.qty + EXCLUDED.qty)
                   );
        END IF;

        -- ------------------------------------------------------------------
        -- UPDATE POSITION for seller (reduce qty)
        -- ------------------------------------------------------------------
        UPDATE position
           SET qty = qty - v_fill_qty
         WHERE account_id    = v_seller_account_id
           AND instrument_id = v_incoming.instrument_id;

        -- Defensive: ensure we didn't go negative (belt-and-suspenders; CHECK constraint fires if so)
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'match_and_settle: seller account % has no position in instrument %.',
                v_seller_account_id, v_incoming.instrument_id;
        END IF;

        -- ------------------------------------------------------------------
        -- INSERT CASH_LEDGER entries (debit buyer, credit seller)
        --   Amount sign convention: positive = money received, negative = money paid
        -- ------------------------------------------------------------------

        -- Buyer pays (negative = debit)
        INSERT INTO cash_ledger (account_id, trade_id, entry_type, amount, value_date)
        VALUES (
            v_buyer_account_id,
            v_trade_id,
            'BUY',
            -(v_settlement_amount),   -- debit
            CURRENT_DATE
        );

        -- Seller receives (positive = credit)
        INSERT INTO cash_ledger (account_id, trade_id, entry_type, amount, value_date)
        VALUES (
            v_seller_account_id,
            v_trade_id,
            'SELL',
            v_settlement_amount,      -- credit
            CURRENT_DATE
        );

        -- ------------------------------------------------------------------
        -- UPDATE ACCOUNT.Cash_balance for both sides
        -- ------------------------------------------------------------------
        UPDATE account
           SET cash_balance = cash_balance - v_settlement_amount
         WHERE account_id = v_buyer_account_id;

        UPDATE account
           SET cash_balance = cash_balance + v_settlement_amount
         WHERE account_id = v_seller_account_id;

        -- ------------------------------------------------------------------
        -- Refresh local copy of incoming order (the fill_qty_sync trigger
        -- already updated it; re-read to get current filled_qty for the loop)
        -- ------------------------------------------------------------------
        SELECT * INTO v_incoming
          FROM trade_order
         WHERE order_id = p_order_id;

    END LOOP;

    -- =========================================================================
    -- STEP 5: If incoming order is still OPEN with zero fills, it remains OPEN.
    -- The triggers already handle PARTIAL/FILLED statuses via fill_qty_sync.
    -- =========================================================================

END;
$$;

COMMENT ON PROCEDURE match_and_settle(BIGINT) IS
    'Full order-matching engine for a single LIMIT order. Must be called inside a SERIALIZABLE transaction.
     Loops matching the best resting counter-order (price-time priority) until the incoming order is
     fully filled or no more matches exist. Creates TRADEs, ORDER_FILLs, updates POSITIONs,
     inserts CASH_LEDGER entries, and updates ACCOUNT.Cash_balance.';

-- ===========================================================================
-- END OF match_and_settle
-- ===========================================================================
