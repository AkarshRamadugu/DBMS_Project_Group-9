-- =============================================================================
-- FILE: db/triggers/001_triggers.sql
-- PROJECT: Paper-Trading Exchange — Group 9, CS F212 Database Systems
-- DESCRIPTION:
--   Five trigger functions + their trigger bindings:
--     1. audit_log_trigger          — AFTER INSERT/UPDATE/DELETE on main tables
--     2. subtype_disjointness_trigger — BEFORE INSERT on bond / option
--     3. trade_validation_trigger   — BEFORE INSERT on trade
--     4. expired_instrument_trigger — BEFORE INSERT on trade_order
--     5. fill_qty_sync_trigger      — AFTER INSERT on order_fill
-- PostgreSQL 16+   Run AFTER 001_schema.sql
-- =============================================================================


-- ===========================================================================
-- 1. AUDIT LOG TRIGGER
--    Fires AFTER INSERT OR UPDATE OR DELETE on every main table.
--    Records the table name, the mutated row's PK, the operation,
--    and old/new row snapshots as JSONB.
-- ===========================================================================

CREATE OR REPLACE FUNCTION fn_audit_log()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_pk_col  TEXT;
    v_row_id  BIGINT;
    v_old     JSONB;
    v_new     JSONB;
BEGIN
    v_old := CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN row_to_json(OLD)::JSONB ELSE NULL END;
    v_new := CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN row_to_json(NEW)::JSONB ELSE NULL END;

    -- Extract bigint surrogate PK when the table has one; NULL for composite PKs.
    v_pk_col := CASE TG_TABLE_NAME
        WHEN 'user_account' THEN 'user_id'
        WHEN 'account'      THEN 'account_id'
        WHEN 'instrument'   THEN 'instrument_id'
        WHEN 'trade_order'  THEN 'order_id'
        WHEN 'trade'        THEN 'trade_id'
        WHEN 'cash_ledger'  THEN 'ledger_id'
        ELSE NULL
    END;

    IF v_pk_col IS NOT NULL THEN
        v_row_id := (COALESCE(v_new, v_old) ->> v_pk_col)::BIGINT;
    ELSE
        v_row_id := NULL;
    END IF;

    INSERT INTO audit_log (table_name, row_id, action, old_values, new_values, changed_by)
    VALUES (
        TG_TABLE_NAME,
        v_row_id,
        TG_OP,
        v_old,
        v_new,
        current_user
    );

    RETURN NULL;  -- AFTER trigger; return value is ignored for statement triggers
END;
$$;

COMMENT ON FUNCTION fn_audit_log() IS
    'Generic audit trigger function. Writes one row to audit_log per DML event.';

-- Attach to all main tables
-- user_account
DROP TRIGGER IF EXISTS trg_audit_user_account ON user_account;
CREATE TRIGGER trg_audit_user_account
    AFTER INSERT OR UPDATE OR DELETE ON user_account
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

-- account
DROP TRIGGER IF EXISTS trg_audit_account ON account;
CREATE TRIGGER trg_audit_account
    AFTER INSERT OR UPDATE OR DELETE ON account
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

-- instrument
DROP TRIGGER IF EXISTS trg_audit_instrument ON instrument;
CREATE TRIGGER trg_audit_instrument
    AFTER INSERT OR UPDATE OR DELETE ON instrument
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

-- trade_order
DROP TRIGGER IF EXISTS trg_audit_trade_order ON trade_order;
CREATE TRIGGER trg_audit_trade_order
    AFTER INSERT OR UPDATE OR DELETE ON trade_order
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

-- trade
DROP TRIGGER IF EXISTS trg_audit_trade ON trade;
CREATE TRIGGER trg_audit_trade
    AFTER INSERT OR UPDATE OR DELETE ON trade
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

-- position
DROP TRIGGER IF EXISTS trg_audit_position ON position;
CREATE TRIGGER trg_audit_position
    AFTER INSERT OR UPDATE OR DELETE ON position
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

-- cash_ledger
DROP TRIGGER IF EXISTS trg_audit_cash_ledger ON cash_ledger;
CREATE TRIGGER trg_audit_cash_ledger
    AFTER INSERT OR UPDATE OR DELETE ON cash_ledger
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();


-- ===========================================================================
-- 2. SUBTYPE DISJOINTNESS TRIGGER
--    Fires BEFORE INSERT on bond and option.
--    Ensures the parent instrument row has the correct instrument_type,
--    enforcing the EER disjoint partial specialisation constraint.
-- ===========================================================================

CREATE OR REPLACE FUNCTION fn_subtype_disjointness()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_instrument_type TEXT;
    v_expected        TEXT;
BEGIN
    -- Determine which subtype table is being inserted into
    IF TG_TABLE_NAME = 'bond' THEN
        v_expected := 'BOND';
    ELSIF TG_TABLE_NAME = 'option' THEN
        v_expected := 'OPTION';
    ELSE
        -- Should never happen; permit silently for other tables
        RETURN NEW;
    END IF;

    SELECT instrument_type
      INTO v_instrument_type
      FROM instrument
     WHERE instrument_id = NEW.instrument_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Subtype disjointness violation: instrument_id % does not exist in instrument table.',
            NEW.instrument_id;
    END IF;

    IF v_instrument_type <> v_expected THEN
        RAISE EXCEPTION
            'Subtype disjointness violation: cannot insert into % because instrument_id % has instrument_type = % (expected %).',
            TG_TABLE_NAME, NEW.instrument_id, v_instrument_type, v_expected
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION fn_subtype_disjointness() IS
    'Enforces EER disjoint specialisation: a row in bond/option must have matching instrument_type in the supertype.';

-- Attach to bond
DROP TRIGGER IF EXISTS trg_subtype_bond ON bond;
CREATE TRIGGER trg_subtype_bond
    BEFORE INSERT ON bond
    FOR EACH ROW EXECUTE FUNCTION fn_subtype_disjointness();

-- Attach to option
DROP TRIGGER IF EXISTS trg_subtype_option ON option;
CREATE TRIGGER trg_subtype_option
    BEFORE INSERT ON option
    FOR EACH ROW EXECUTE FUNCTION fn_subtype_disjointness();


-- ===========================================================================
-- 3. TRADE VALIDATION TRIGGER
--    Fires BEFORE INSERT on trade.
--    Checks:
--      a) buy_order and sell_order must trade the same instrument_id
--      b) buy_order.side = 'BUY' and sell_order.side = 'SELL'
-- ===========================================================================

CREATE OR REPLACE FUNCTION fn_trade_validation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_buy_instrument  BIGINT;
    v_sell_instrument BIGINT;
    v_buy_side        TEXT;
    v_sell_side       TEXT;
BEGIN
    SELECT instrument_id, side
      INTO v_buy_instrument, v_buy_side
      FROM trade_order
     WHERE order_id = NEW.buy_order_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Trade validation: buy_order_id % does not exist.', NEW.buy_order_id;
    END IF;

    SELECT instrument_id, side
      INTO v_sell_instrument, v_sell_side
      FROM trade_order
     WHERE order_id = NEW.sell_order_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Trade validation: sell_order_id % does not exist.', NEW.sell_order_id;
    END IF;

    -- Same instrument check
    IF v_buy_instrument <> v_sell_instrument THEN
        RAISE EXCEPTION
            'Trade validation: buy_order instrument_id (%) != sell_order instrument_id (%).',
            v_buy_instrument, v_sell_instrument
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- Opposite sides check
    IF v_buy_side <> 'BUY' THEN
        RAISE EXCEPTION
            'Trade validation: order % designated as buy_order but has side = %.',
            NEW.buy_order_id, v_buy_side
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF v_sell_side <> 'SELL' THEN
        RAISE EXCEPTION
            'Trade validation: order % designated as sell_order but has side = %.',
            NEW.sell_order_id, v_sell_side
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION fn_trade_validation() IS
    'Ensures buy and sell legs of a trade reference the same instrument and correct sides.';

DROP TRIGGER IF EXISTS trg_trade_validation ON trade;
CREATE TRIGGER trg_trade_validation
    BEFORE INSERT ON trade
    FOR EACH ROW EXECUTE FUNCTION fn_trade_validation();


-- ===========================================================================
-- 4. EXPIRED INSTRUMENT TRIGGER
--    Fires BEFORE INSERT on trade_order.
--    Rejects orders placed on instruments with status = 'EXPIRED'.
-- ===========================================================================

CREATE OR REPLACE FUNCTION fn_expired_instrument()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_status TEXT;
BEGIN
    SELECT status
      INTO v_status
      FROM instrument
     WHERE instrument_id = NEW.instrument_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Expired-instrument check: instrument_id % does not exist.',
            NEW.instrument_id;
    END IF;

    IF v_status = 'EXPIRED' THEN
        RAISE EXCEPTION
            'Expired-instrument check: instrument_id % (%) has status EXPIRED — orders are not accepted.',
            NEW.instrument_id, v_status
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION fn_expired_instrument() IS
    'Rejects INSERT on trade_order when the instrument is EXPIRED.';

DROP TRIGGER IF EXISTS trg_expired_instrument ON trade_order;
CREATE TRIGGER trg_expired_instrument
    BEFORE INSERT ON trade_order
    FOR EACH ROW EXECUTE FUNCTION fn_expired_instrument();


-- ===========================================================================
-- 5. FILL QTY SYNC TRIGGER
--    Fires AFTER INSERT on order_fill.
--    Recomputes trade_order.filled_qty as the SUM of all matching order_fill.qty
--    rows, then sets status to 'FILLED' or 'PARTIAL' accordingly.
--    Also validates that the fill's order_id is a leg of its trade_id
--    (the ORDER_FILL integrity rule from spec §1.5).
-- ===========================================================================

CREATE OR REPLACE FUNCTION fn_fill_qty_sync()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_total_filled INTEGER;
    v_order_qty    INTEGER;
    v_new_status   TEXT;
    v_buy_order_id  BIGINT;
    v_sell_order_id BIGINT;
BEGIN
    -- ---- Integrity check: order_id must be a leg of trade_id ----------------
    SELECT buy_order_id, sell_order_id
      INTO v_buy_order_id, v_sell_order_id
      FROM trade
     WHERE trade_id = NEW.trade_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Fill sync: trade_id % does not exist.', NEW.trade_id;
    END IF;

    IF NEW.order_id NOT IN (v_buy_order_id, v_sell_order_id) THEN
        RAISE EXCEPTION
            'Fill sync: order_id % is not a leg (buy=%, sell=%) of trade_id %.',
            NEW.order_id, v_buy_order_id, v_sell_order_id, NEW.trade_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- ---- Recompute filled_qty ------------------------------------------------
    SELECT COALESCE(SUM(f.qty), 0), o.qty
      INTO v_total_filled, v_order_qty
      FROM order_fill f
      JOIN trade_order o ON o.order_id = f.order_id
     WHERE f.order_id = NEW.order_id
     GROUP BY o.qty;

    -- Determine new status
    IF v_total_filled >= v_order_qty THEN
        v_new_status := 'FILLED';
    ELSE
        v_new_status := 'PARTIAL';
    END IF;

    UPDATE trade_order
       SET filled_qty = v_total_filled,
           status     = v_new_status
     WHERE order_id = NEW.order_id;

    RETURN NULL;  -- AFTER trigger; return value not used
END;
$$;

COMMENT ON FUNCTION fn_fill_qty_sync() IS
    'After each order_fill insert: recomputes filled_qty and updates order status to PARTIAL/FILLED.';

DROP TRIGGER IF EXISTS trg_fill_qty_sync ON order_fill;
CREATE TRIGGER trg_fill_qty_sync
    AFTER INSERT ON order_fill
    FOR EACH ROW EXECUTE FUNCTION fn_fill_qty_sync();


-- ===========================================================================
-- END OF TRIGGERS
-- ===========================================================================
