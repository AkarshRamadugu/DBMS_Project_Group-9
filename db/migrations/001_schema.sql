-- =============================================================================
-- FILE: db/migrations/001_schema.sql
-- PROJECT: Paper-Trading Exchange — Group 9, CS F212 Database Systems
--          BITS Pilani Hyderabad
-- AUTHORS: Devansh Anadkat, Akarsh Ramadugu, Shashank Bodala,
--          Druhin Bommisetti, Hakimkari Sathvika
-- DATE: 2026-11-10
--
-- DESCRIPTION:
--   Complete DDL for all 12 relations of the Paper-Trading Exchange.
--   Schema follows the 9-step ER→Relational mapping (Elmasri & Navathe 7e).
--   Relations (12):
--     1. user_account   — platform users (renamed from USER, reserved word)
--     2. account        — trading accounts (cash + house flag)
--     3. instrument     — supertype for all tradeable instruments
--     4. bond           — subtype of instrument for bonds
--     5. option         — subtype of instrument for options
--     6. price_bar      — daily OHLCV bars (weak entity)
--     7. trade_order    — limit orders (renamed from ORDER, reserved word)
--     8. trade          — matched & executed fills
--     9. order_fill     — per-order-per-trade fill records (weak entity)
--    10. position       — M:N HOLDS (account × instrument with Qty, Avg_cost)
--    11. cash_ledger    — double-entry style ledger for all cash movements
--    12. audit_log      — immutable change log (no FK by design)
--
-- PostgreSQL 16+   Run as: psql -d <dbname> -f 001_schema.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 0. Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- for gen_random_uuid() if needed


-- ===========================================================================
-- 1. USER_ACCOUNT  (Step 1 — regular strong entity; renamed from USER)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS user_account (
    user_id       BIGSERIAL    PRIMARY KEY,
    name          TEXT         NOT NULL,
    email         TEXT         NOT NULL,
    password_hash TEXT         NOT NULL,
    role          TEXT         NOT NULL DEFAULT 'TRADER'
                                   CHECK (role IN ('ADMIN', 'TRADER')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_user_email UNIQUE (email)
);

COMMENT ON TABLE  user_account             IS 'Platform users. Renamed from USER (reserved word).';
COMMENT ON COLUMN user_account.role        IS 'ADMIN or TRADER.';
COMMENT ON COLUMN user_account.password_hash IS 'bcrypt / argon2 hash — never store plaintext.';


-- ===========================================================================
-- 2. ACCOUNT  (Step 1 + Step 4: 1:N OWNS from USER)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS account (
    account_id    BIGSERIAL    PRIMARY KEY,
    user_id       BIGINT       NOT NULL
                                   REFERENCES user_account (user_id)
                                   ON DELETE RESTRICT,
    cash_balance  NUMERIC(20, 6) NOT NULL DEFAULT 0,
    is_house      BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_account_cash_balance CHECK (cash_balance >= 0)
);

COMMENT ON TABLE  account              IS 'Trading accounts owned by users. is_house=TRUE marks the house inventory account.';
COMMENT ON COLUMN account.cash_balance IS 'Denormalised for performance; maintained atomically within settlement transactions.';


-- ===========================================================================
-- 3. INSTRUMENT  (Step 1 — supertype)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS instrument (
    instrument_id   BIGSERIAL    PRIMARY KEY,
    symbol          TEXT         NOT NULL,
    name            TEXT         NOT NULL,
    instrument_type TEXT         NOT NULL
                                     CHECK (instrument_type IN ('STOCK', 'BOND', 'OPTION')),
    sector          TEXT,
    multiplier      NUMERIC(12, 6) NOT NULL DEFAULT 1
                                     CHECK (multiplier > 0),
    tick_size       NUMERIC(12, 6) NOT NULL DEFAULT 0.05
                                     CHECK (tick_size > 0),
    lot_size        INTEGER      NOT NULL DEFAULT 1
                                     CHECK (lot_size > 0),
    status          TEXT         NOT NULL DEFAULT 'ACTIVE'
                                     CHECK (status IN ('ACTIVE', 'HALTED', 'EXPIRED')),

    CONSTRAINT uq_instrument_symbol UNIQUE (symbol)
);

COMMENT ON TABLE  instrument                 IS 'Supertype for all tradeable instruments (stocks, bonds, options).';
COMMENT ON COLUMN instrument.multiplier      IS 'Settlement multiplier: 1 for stocks, face_value/100 for bonds, contract_size for options.';
COMMENT ON COLUMN instrument.instrument_type IS 'Discriminating attribute for EER disjoint partial specialisation.';


-- ===========================================================================
-- 4. BOND  (Step 8A — subtype relation; PK = FK → instrument)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS bond (
    instrument_id    BIGINT       PRIMARY KEY
                                     REFERENCES instrument (instrument_id)
                                     ON DELETE CASCADE,
    face_value       NUMERIC(20, 6) NOT NULL
                                     CHECK (face_value > 0),
    coupon_rate      NUMERIC(8, 6)  NOT NULL
                                     CHECK (coupon_rate >= 0),
    coupon_frequency INTEGER      NOT NULL
                                     CHECK (coupon_frequency IN (1, 2, 4, 12)),
    issue_date       DATE         NOT NULL,
    maturity_date    DATE         NOT NULL,

    CONSTRAINT chk_bond_maturity CHECK (maturity_date > issue_date)
);

COMMENT ON TABLE bond IS 'Bond subtype. coupon_frequency: 1=annual, 2=semi-annual, 4=quarterly, 12=monthly.';


-- ===========================================================================
-- 5. OPTION  (Step 8A — subtype + Step 4: HAS_UNDERLYING FK)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS option (
    instrument_id  BIGINT       PRIMARY KEY
                                   REFERENCES instrument (instrument_id)
                                   ON DELETE CASCADE,
    underlying_id  BIGINT       NOT NULL
                                   REFERENCES instrument (instrument_id)
                                   ON DELETE RESTRICT,
    strike         NUMERIC(20, 6) NOT NULL
                                   CHECK (strike > 0),
    expiry         DATE         NOT NULL,
    option_type    TEXT         NOT NULL
                                   CHECK (option_type IN ('CALL', 'PUT'))
);

COMMENT ON TABLE option IS 'Option subtype. underlying_id → instrument(instrument_id) for HAS_UNDERLYING relationship.';


-- ===========================================================================
-- 6. PRICE_BAR  (Step 2 — weak entity; PK = instrument_id + trade_date)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS price_bar (
    instrument_id  BIGINT       NOT NULL
                                   REFERENCES instrument (instrument_id)
                                   ON DELETE CASCADE,
    trade_date     DATE         NOT NULL,
    open           NUMERIC(20, 6) NOT NULL CHECK (open  > 0),
    high           NUMERIC(20, 6) NOT NULL CHECK (high  > 0),
    low            NUMERIC(20, 6) NOT NULL CHECK (low   > 0),
    close          NUMERIC(20, 6) NOT NULL CHECK (close > 0),
    volume         BIGINT       NOT NULL DEFAULT 0,

    CONSTRAINT pk_price_bar         PRIMARY KEY (instrument_id, trade_date),
    CONSTRAINT chk_price_bar_hl     CHECK (high >= low),
    CONSTRAINT chk_price_bar_open   CHECK (open  > 0),
    CONSTRAINT chk_price_bar_close  CHECK (close > 0)
);

COMMENT ON TABLE price_bar IS 'Daily OHLCV bars — weak entity identified by (instrument_id, trade_date).';


-- ===========================================================================
-- 7. TRADE_ORDER  (Step 1 + Step 4: PLACES, FOR FKs; renamed from ORDER)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS trade_order (
    order_id      BIGSERIAL    PRIMARY KEY,
    account_id    BIGINT       NOT NULL
                                   REFERENCES account (account_id)
                                   ON DELETE RESTRICT,
    instrument_id BIGINT       NOT NULL
                                   REFERENCES instrument (instrument_id)
                                   ON DELETE RESTRICT,
    side          TEXT         NOT NULL
                                   CHECK (side IN ('BUY', 'SELL')),
    price         NUMERIC(20, 6) NOT NULL
                                   CHECK (price > 0),
    qty           INTEGER      NOT NULL
                                   CHECK (qty > 0),
    filled_qty    INTEGER      NOT NULL DEFAULT 0,
    status        TEXT         NOT NULL DEFAULT 'OPEN'
                                   CHECK (status IN ('OPEN', 'PARTIAL', 'FILLED', 'CANCELLED')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_order_filled_qty CHECK (filled_qty BETWEEN 0 AND qty)
);

COMMENT ON TABLE  trade_order            IS 'Limit orders. Renamed from ORDER (reserved word).';
COMMENT ON COLUMN trade_order.filled_qty IS 'Denormalised; kept in sync by fill_qty_sync_trigger on order_fill.';


-- ===========================================================================
-- 8. TRADE  (Step 1 + Step 4: BUY_SIDE, SELL_SIDE FKs)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS trade (
    trade_id      BIGSERIAL    PRIMARY KEY,
    buy_order_id  BIGINT       NOT NULL
                                   REFERENCES trade_order (order_id)
                                   ON DELETE RESTRICT,
    sell_order_id BIGINT       NOT NULL
                                   REFERENCES trade_order (order_id)
                                   ON DELETE RESTRICT,
    price         NUMERIC(20, 6) NOT NULL CHECK (price > 0),
    qty           INTEGER      NOT NULL CHECK (qty > 0),
    executed_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE trade IS 'Executed matches between a buy and a sell order.';


-- ===========================================================================
-- 9. ORDER_FILL  (Step 2 — weak entity; PK = order_id + fill_seq)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS order_fill (
    order_id   BIGINT       NOT NULL
                                REFERENCES trade_order (order_id)
                                ON DELETE CASCADE,
    fill_seq   INTEGER      NOT NULL,                  -- partial key
    trade_id   BIGINT       NOT NULL
                                REFERENCES trade (trade_id)
                                ON DELETE RESTRICT,
    qty        INTEGER      NOT NULL CHECK (qty > 0),
    price      NUMERIC(20, 6) NOT NULL CHECK (price > 0),
    filled_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_order_fill PRIMARY KEY (order_id, fill_seq)
);

COMMENT ON TABLE order_fill IS 'Per-order-per-trade fill record — weak entity identified by (order_id, fill_seq).';


-- ===========================================================================
-- 10. POSITION  (Step 5 — M:N HOLDS; PK = account_id + instrument_id)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS position (
    account_id    BIGINT         NOT NULL
                                     REFERENCES account (account_id)
                                     ON DELETE CASCADE,
    instrument_id BIGINT         NOT NULL
                                     REFERENCES instrument (instrument_id)
                                     ON DELETE RESTRICT,
    qty           INTEGER        NOT NULL DEFAULT 0
                                     CHECK (qty >= 0),
    avg_cost      NUMERIC(20, 6) NOT NULL DEFAULT 0
                                     CHECK (avg_cost >= 0),

    CONSTRAINT pk_position PRIMARY KEY (account_id, instrument_id)
);

COMMENT ON TABLE position IS 'M:N HOLDS relation. qty >= 0 enforces no short-selling.';


-- ===========================================================================
-- 11. CASH_LEDGER  (Step 1 + Step 4: LEDGER_FOR, SETTLES, CONCERNS FKs)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS cash_ledger (
    ledger_id     BIGSERIAL    PRIMARY KEY,
    account_id    BIGINT       NOT NULL
                                   REFERENCES account (account_id)
                                   ON DELETE RESTRICT,
    -- trade_id and instrument_id are both nullable (partial participation)
    trade_id      BIGINT
                                   REFERENCES trade (trade_id)
                                   ON DELETE RESTRICT,
    instrument_id BIGINT
                                   REFERENCES instrument (instrument_id)
                                   ON DELETE RESTRICT,
    entry_type    TEXT         NOT NULL
                                   CHECK (entry_type IN (
                                       'DEPOSIT', 'WITHDRAWAL', 'BUY', 'SELL',
                                       'FEE', 'COUPON', 'REDEMPTION', 'EXERCISE'
                                   )),
    amount        NUMERIC(20, 6) NOT NULL
                                   CHECK (amount <> 0),
    value_date    DATE         NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Idempotency guard: prevents double coupon / redemption payouts
    CONSTRAINT uq_cash_ledger_idempotent
        UNIQUE (account_id, instrument_id, entry_type, value_date),

    -- trade_id and instrument_id must never both be non-NULL
    CONSTRAINT chk_cash_ledger_mutex
        CHECK (NOT (trade_id IS NOT NULL AND instrument_id IS NOT NULL))
);

COMMENT ON TABLE  cash_ledger              IS 'All cash movements. trade_id OR instrument_id link the entry — never both.';
COMMENT ON COLUMN cash_ledger.amount       IS 'Positive = credit (money in), negative = debit (money out).';
COMMENT ON COLUMN cash_ledger.entry_type   IS 'DEPOSIT/WITHDRAWAL: manual; BUY/SELL: settlement; FEE/COUPON/REDEMPTION/EXERCISE: instrument-linked.';


-- ===========================================================================
-- 12. AUDIT_LOG  (Step 1 — no FK by design so history survives deletes)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    log_id      BIGSERIAL    PRIMARY KEY,
    table_name  TEXT         NOT NULL,
    row_id      BIGINT,                   -- nullable: composite PKs logged as JSONB
    action      TEXT         NOT NULL
                                 CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    old_values  JSONB,
    new_values  JSONB,
    changed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    changed_by  TEXT                      -- optional: session user
);

COMMENT ON TABLE  audit_log            IS 'Immutable change log. No FK so entries survive referenced-row deletions.';
COMMENT ON COLUMN audit_log.old_values IS 'row_to_json(OLD) cast to JSONB — NULL for INSERT.';
COMMENT ON COLUMN audit_log.new_values IS 'row_to_json(NEW) cast to JSONB — NULL for DELETE.';


-- ===========================================================================
-- INDEXES
-- ===========================================================================

-- Partial index on trade_order for order-book lookups (open/partial orders only)
-- Covers: instrument_id filter + side filter + price ordering + created_at tiebreak
CREATE INDEX IF NOT EXISTS idx_trade_order_book
    ON trade_order (instrument_id, side, price, created_at)
    WHERE status IN ('OPEN', 'PARTIAL');

COMMENT ON INDEX idx_trade_order_book IS 'Partial index for fast order-book scans — only open/partial orders.';

-- Index on price_bar for latest-price queries (most recent trade_date first)
CREATE INDEX IF NOT EXISTS idx_price_bar_latest
    ON price_bar (instrument_id, trade_date DESC);

COMMENT ON INDEX idx_price_bar_latest IS 'Covers "SELECT ... ORDER BY trade_date DESC LIMIT 1" per instrument.';

-- Supporting indexes for common FK-join patterns
CREATE INDEX IF NOT EXISTS idx_account_user       ON account      (user_id);
CREATE INDEX IF NOT EXISTS idx_order_account      ON trade_order  (account_id);
CREATE INDEX IF NOT EXISTS idx_order_instrument   ON trade_order  (instrument_id);
CREATE INDEX IF NOT EXISTS idx_trade_buy_order    ON trade        (buy_order_id);
CREATE INDEX IF NOT EXISTS idx_trade_sell_order   ON trade        (sell_order_id);
CREATE INDEX IF NOT EXISTS idx_order_fill_trade   ON order_fill   (trade_id);
CREATE INDEX IF NOT EXISTS idx_cash_ledger_account ON cash_ledger (account_id);
CREATE INDEX IF NOT EXISTS idx_cash_ledger_trade  ON cash_ledger  (trade_id)
    WHERE trade_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_position_account   ON position     (account_id);

-- ===========================================================================
-- END OF SCHEMA
-- ===========================================================================
