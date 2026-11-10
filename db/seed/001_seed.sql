-- =============================================================================
-- FILE: db/seed/001_seed.sql
-- PROJECT: Paper-Trading Exchange — Group 9, CS F212 Database Systems
-- DESCRIPTION:
--   Seed data for a realistic development / demo environment:
--     • 2 users (1 admin, 1 trader)
--     • 3 accounts (1 house, 2 trader accounts)
--     • 10 instruments:
--         5 NSE stocks  : RELIANCE, TCS, INFY, HDFCBANK, WIPRO
--         1 INDEX       : NIFTY (underlying for options)
--         2 GOI bonds   : GOI_2030, GOI_2035
--         2 NIFTY options: NIFTY_CE_25000_DEC2026, NIFTY_PE_25000_DEC2026
--     • 10 trading days of OHLCV bars for every instrument
--     • Initial positions in the house account
--     • Initial cash deposits in cash_ledger + account.cash_balance
--
-- NOTES:
--   • Passwords are bcrypt hashes of the literal strings shown in comments.
--   • Price bars use generate_series offset from '2026-11-10'.
--   • ON CONFLICT DO NOTHING on most inserts makes the script re-runnable.
-- PostgreSQL 16+   Run AFTER all migrations, triggers, and views.
-- =============================================================================

BEGIN;

-- ===========================================================================
-- 1. USERS
--    user 1: admin  (password: "AdminPass123!")
--    user 2: trader (password: "TraderPass123!")
-- ===========================================================================

INSERT INTO user_account (user_id, name, email, password_hash, role, created_at)
VALUES
    (1, 'Admin User',    'admin@papertrade.local',
     '$2b$12$LHYlMjPFJY6mW0zC0BjpwuPQWNpxYcN3TyFxJZ6wGm8dUqN.FeM7G',  -- AdminPass123!
     'ADMIN',  '2026-01-01 00:00:00+00'),
    (2, 'Alice Trader',  'alice@papertrade.local',
     '$2b$12$H4kP8mVJM.0J3n7WqIv0FuLwM9XYbN5KtGhDxA2cRs1eQoPz4yUim',  -- TraderPass123!
     'TRADER', '2026-01-02 00:00:00+00'),
    (3, 'Bob Trader',    'bob@papertrade.local',
     '$2b$12$H4kP8mVJM.0J3n7WqIv0FuLwM9XYbN5KtGhDxA2cRs1eQoPz4yUim',  -- TraderPass123!
     'TRADER', '2026-01-03 00:00:00+00')
ON CONFLICT (email) DO NOTHING;

-- Sync sequence
SELECT setval('user_account_user_id_seq', GREATEST((SELECT MAX(user_id) FROM user_account), 1));


-- ===========================================================================
-- 2. ACCOUNTS
--    account 1: house account (admin user)
--    account 2: Alice's trading account
--    account 3: Bob's trading account
-- ===========================================================================

INSERT INTO account (account_id, user_id, cash_balance, is_house, created_at)
VALUES
    (1, 1, 50000000.00, TRUE,  '2026-01-01 00:00:00+00'),  -- House: ₹5 crore
    (2, 2,  2000000.00, FALSE, '2026-01-02 00:00:00+00'),  -- Alice: ₹20 lakh
    (3, 3,  1500000.00, FALSE, '2026-01-03 00:00:00+00')   -- Bob:   ₹15 lakh
ON CONFLICT (account_id) DO NOTHING;

SELECT setval('account_account_id_seq', GREATEST((SELECT MAX(account_id) FROM account), 1));


-- ===========================================================================
-- 3. INSTRUMENTS
-- ===========================================================================

-- ---- 3a. NSE Stocks (multiplier = 1, lot_size = 1) -------------------------
INSERT INTO instrument
    (instrument_id, symbol, name, instrument_type, sector, multiplier, tick_size, lot_size, status)
VALUES
    (1,  'RELIANCE',  'Reliance Industries Ltd',           'STOCK', 'Energy',          1, 0.05, 1, 'ACTIVE'),
    (2,  'TCS',       'Tata Consultancy Services Ltd',     'STOCK', 'IT',               1, 0.05, 1, 'ACTIVE'),
    (3,  'INFY',      'Infosys Ltd',                       'STOCK', 'IT',               1, 0.05, 1, 'ACTIVE'),
    (4,  'HDFCBANK',  'HDFC Bank Ltd',                     'STOCK', 'Banking',          1, 0.05, 1, 'ACTIVE'),
    (5,  'WIPRO',     'Wipro Ltd',                         'STOCK', 'IT',               1, 0.05, 1, 'ACTIVE'),
-- ---- 3b. NIFTY Index (underlying for options) --------------------------------
    (6,  'NIFTY',     'NIFTY 50 Index',                    'STOCK', 'Index',            1, 0.05, 1, 'ACTIVE'),
-- ---- 3c. GOI Bonds (multiplier = face_value/100 = 10000/100 = 100) ----------
    (7,  'GOI_2030',  'Govt of India 7.26% 2030',          'BOND',  'Government',     100, 0.01, 1, 'ACTIVE'),
    (8,  'GOI_2035',  'Govt of India 7.18% 2035',          'BOND',  'Government',     100, 0.01, 1, 'ACTIVE'),
-- ---- 3d. NIFTY Options (lot_size = 50, multiplier = 50) ---------------------
    (9,  'NIFTY_CE_25000_DEC2026', 'NIFTY 25000 CALL DEC 2026', 'OPTION', 'Derivatives', 50, 0.05, 50, 'ACTIVE'),
    (10, 'NIFTY_PE_25000_DEC2026', 'NIFTY 25000 PUT DEC 2026',  'OPTION', 'Derivatives', 50, 0.05, 50, 'ACTIVE')
ON CONFLICT (symbol) DO NOTHING;

SELECT setval('instrument_instrument_id_seq', GREATEST((SELECT MAX(instrument_id) FROM instrument), 1));


-- ---- 3e. Bond subtype rows ---------------------------------------------------
INSERT INTO bond (instrument_id, face_value, coupon_rate, coupon_frequency, issue_date, maturity_date)
VALUES
    (7, 10000.00, 0.0726, 2, '2020-01-15', '2030-01-15'),  -- 7.26% semi-annual
    (8, 10000.00, 0.0718, 2, '2021-07-01', '2035-07-01')   -- 7.18% semi-annual
ON CONFLICT (instrument_id) DO NOTHING;


-- ---- 3f. Option subtype rows -------------------------------------------------
INSERT INTO option (instrument_id, underlying_id, strike, expiry, option_type)
VALUES
    (9,  6, 25000.00, '2026-12-31', 'CALL'),   -- NIFTY 25000 CE Dec 2026
    (10, 6, 25000.00, '2026-12-31', 'PUT')     -- NIFTY 25000 PE Dec 2026
ON CONFLICT (instrument_id) DO NOTHING;


-- ===========================================================================
-- 4. PRICE BARS — 10 trading days ending 2026-11-10
--    Generated using generate_series. Realistic but synthetic OHLCV.
--    Each stock has a base price; daily variation ±1-2%.
-- ===========================================================================

-- Helper: generate 10 trading days (Mon–Fri, excluding weekends)
-- For simplicity we generate 10 calendar days and approximate.
-- In production these would be loaded via COPY from NSE bhavcopy CSVs.

-- ---- RELIANCE (base ≈ ₹2,900) -----------------------------------------------
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    1 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((2900 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 12
           + SIN(ROW_NUMBER() OVER (ORDER BY gs)) * 15)::NUMERIC, 2) AS open,
    ROUND((2900 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 12
           + SIN(ROW_NUMBER() OVER (ORDER BY gs)) * 15 + 25)::NUMERIC, 2) AS high,
    ROUND((2900 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 12
           + SIN(ROW_NUMBER() OVER (ORDER BY gs)) * 15 - 20)::NUMERIC, 2) AS low,
    ROUND((2900 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 12
           + COS(ROW_NUMBER() OVER (ORDER BY gs)) * 18)::NUMERIC, 2) AS close,
    (1500000 + ROW_NUMBER() OVER (ORDER BY gs) * 50000)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)   -- exclude weekends
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;

-- ---- TCS (base ≈ ₹3,900) ----------------------------------------------------
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    2 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((3900 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 15
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.3) * 20)::NUMERIC, 2) AS open,
    ROUND((3900 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 15
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.3) * 20 + 30)::NUMERIC, 2) AS high,
    ROUND((3900 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 15
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.3) * 20 - 25)::NUMERIC, 2) AS low,
    ROUND((3900 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 15
           + COS(ROW_NUMBER() OVER (ORDER BY gs) * 1.3) * 22)::NUMERIC, 2) AS close,
    (800000 + ROW_NUMBER() OVER (ORDER BY gs) * 30000)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;

-- ---- INFY (base ≈ ₹1,850) ---------------------------------------------------
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    3 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((1850 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 8
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 0.9) * 12)::NUMERIC, 2) AS open,
    ROUND((1850 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 8
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 0.9) * 12 + 18)::NUMERIC, 2) AS high,
    ROUND((1850 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 8
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 0.9) * 12 - 15)::NUMERIC, 2) AS low,
    ROUND((1850 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 8
           + COS(ROW_NUMBER() OVER (ORDER BY gs) * 0.9) * 14)::NUMERIC, 2) AS close,
    (2000000 + ROW_NUMBER() OVER (ORDER BY gs) * 60000)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;

-- ---- HDFCBANK (base ≈ ₹1,780) -----------------------------------------------
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    4 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((1780 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 7
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.1) * 10)::NUMERIC, 2) AS open,
    ROUND((1780 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 7
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.1) * 10 + 15)::NUMERIC, 2) AS high,
    ROUND((1780 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 7
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.1) * 10 - 12)::NUMERIC, 2) AS low,
    ROUND((1780 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 7
           + COS(ROW_NUMBER() OVER (ORDER BY gs) * 1.1) * 11)::NUMERIC, 2) AS close,
    (3500000 + ROW_NUMBER() OVER (ORDER BY gs) * 80000)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;

-- ---- WIPRO (base ≈ ₹560) ----------------------------------------------------
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    5 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((560 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 3
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.5) * 5)::NUMERIC, 2) AS open,
    ROUND((560 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 3
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.5) * 5 + 8)::NUMERIC, 2) AS high,
    ROUND((560 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 3
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.5) * 5 - 6)::NUMERIC, 2) AS low,
    ROUND((560 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 3
           + COS(ROW_NUMBER() OVER (ORDER BY gs) * 1.5) * 4)::NUMERIC, 2) AS close,
    (5000000 + ROW_NUMBER() OVER (ORDER BY gs) * 100000)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;

-- ---- NIFTY Index (base ≈ 24,500) --------------------------------------------
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    6 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((24500 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 50
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 0.7) * 100)::NUMERIC, 2) AS open,
    ROUND((24500 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 50
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 0.7) * 100 + 150)::NUMERIC, 2) AS high,
    ROUND((24500 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 50
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 0.7) * 100 - 120)::NUMERIC, 2) AS low,
    ROUND((24500 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 50
           + COS(ROW_NUMBER() OVER (ORDER BY gs) * 0.7) * 90)::NUMERIC, 2) AS close,
    (200000000 + ROW_NUMBER() OVER (ORDER BY gs) * 5000000)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;

-- ---- GOI_2030 Bond (clean price ≈ ₹98.50 per ₹100 face; we store as 98.50) -
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    7 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((98.50 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 0.02
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 2.0) * 0.05)::NUMERIC, 4) AS open,
    ROUND((98.50 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 0.02
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 2.0) * 0.05 + 0.08)::NUMERIC, 4) AS high,
    ROUND((98.50 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 0.02
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 2.0) * 0.05 - 0.06)::NUMERIC, 4) AS low,
    ROUND((98.50 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 0.02
           + COS(ROW_NUMBER() OVER (ORDER BY gs) * 2.0) * 0.04)::NUMERIC, 4) AS close,
    (500 + ROW_NUMBER() OVER (ORDER BY gs) * 20)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;

-- ---- GOI_2035 Bond (clean price ≈ ₹96.80) ------------------------------------
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    8 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((96.80 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 0.03
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.8) * 0.06)::NUMERIC, 4) AS open,
    ROUND((96.80 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 0.03
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.8) * 0.06 + 0.10)::NUMERIC, 4) AS high,
    ROUND((96.80 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 0.03
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.8) * 0.06 - 0.08)::NUMERIC, 4) AS low,
    ROUND((96.80 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 0.03
           + COS(ROW_NUMBER() OVER (ORDER BY gs) * 1.8) * 0.05)::NUMERIC, 4) AS close,
    (300 + ROW_NUMBER() OVER (ORDER BY gs) * 15)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;

-- ---- NIFTY_CE_25000_DEC2026 (synthetic option premium ≈ ₹450) ---------------
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    9 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((450 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 8
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.2) * 15)::NUMERIC, 2) AS open,
    ROUND((450 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 8
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.2) * 15 + 20)::NUMERIC, 2) AS high,
    ROUND((450 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 8
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.2) * 15 - 15)::NUMERIC, 2) AS low,
    ROUND((450 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * 8
           + COS(ROW_NUMBER() OVER (ORDER BY gs) * 1.2) * 12)::NUMERIC, 2) AS close,
    (10000 + ROW_NUMBER() OVER (ORDER BY gs) * 500)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;

-- ---- NIFTY_PE_25000_DEC2026 (synthetic option premium ≈ ₹680) ---------------
INSERT INTO price_bar (instrument_id, trade_date, open, high, low, close, volume)
SELECT
    10 AS instrument_id,
    gs::DATE AS trade_date,
    ROUND((680 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * (-8)
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.4) * 18)::NUMERIC, 2) AS open,
    ROUND((680 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * (-8)
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.4) * 18 + 25)::NUMERIC, 2) AS high,
    ROUND((680 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * (-8)
           + SIN(ROW_NUMBER() OVER (ORDER BY gs) * 1.4) * 18 - 20)::NUMERIC, 2) AS low,
    ROUND((680 + (ROW_NUMBER() OVER (ORDER BY gs) - 5) * (-8)
           + COS(ROW_NUMBER() OVER (ORDER BY gs) * 1.4) * 16)::NUMERIC, 2) AS close,
    (8000 + ROW_NUMBER() OVER (ORDER BY gs) * 400)::BIGINT AS volume
FROM generate_series(
    '2026-10-28'::DATE,
    '2026-11-10'::DATE,
    INTERVAL '1 day'
) gs
WHERE EXTRACT(DOW FROM gs) NOT IN (0, 6)
LIMIT 10
ON CONFLICT (instrument_id, trade_date) DO NOTHING;


-- ===========================================================================
-- 5. INITIAL POSITIONS (house account holds inventory)
-- ===========================================================================

INSERT INTO position (account_id, instrument_id, qty, avg_cost)
VALUES
    -- House account inventory
    (1, 1, 10000, 2850.00),   -- 10,000 RELIANCE @ ₹2,850 avg
    (1, 2,  5000, 3820.00),   -- 5,000 TCS @ ₹3,820 avg
    (1, 3,  8000, 1810.00),   -- 8,000 INFY @ ₹1,810 avg
    (1, 4,  6000, 1750.00),   -- 6,000 HDFCBANK @ ₹1,750 avg
    (1, 5, 15000,  545.00),   -- 15,000 WIPRO @ ₹545 avg
    (1, 7,   500,   98.00),   -- 500 units GOI_2030 @ 98.00 (clean price)
    (1, 8,   300,   96.50),   -- 300 units GOI_2035 @ 96.50
    (1, 9,   200,  420.00),   -- 200 lots NIFTY CE @ ₹420 avg
    (1, 10,  150,  710.00),   -- 150 lots NIFTY PE @ ₹710 avg
    -- Alice's initial position (some RELIANCE bought earlier)
    (2, 1,   100, 2880.00),   -- 100 RELIANCE @ ₹2,880 avg
    (2, 3,    50, 1830.00),   -- 50 INFY @ ₹1,830 avg
    -- Bob's initial position
    (3, 2,    30, 3860.00),   -- 30 TCS @ ₹3,860 avg
    (3, 4,    20, 1760.00)    -- 20 HDFCBANK @ ₹1,760 avg
ON CONFLICT (account_id, instrument_id) DO NOTHING;


-- ===========================================================================
-- 6. INITIAL CASH DEPOSITS (cash_ledger + account.cash_balance already set)
--    Record the opening deposits as DEPOSIT ledger entries.
-- ===========================================================================

INSERT INTO cash_ledger (account_id, instrument_id, trade_id, entry_type, amount, value_date)
VALUES
    (1, NULL, NULL, 'DEPOSIT',  50000000.00, '2026-01-01'),  -- House seed capital
    (2, NULL, NULL, 'DEPOSIT',   2000000.00, '2026-01-02'),  -- Alice deposit
    (3, NULL, NULL, 'DEPOSIT',   1500000.00, '2026-01-03')   -- Bob deposit
ON CONFLICT (account_id, instrument_id, entry_type, value_date) DO NOTHING;


COMMIT;

-- ===========================================================================
-- POST-SEED VERIFICATION QUERIES (run manually to sanity-check)
-- ===========================================================================

/*
-- Count rows in each table:
SELECT 'user_account' AS tbl, COUNT(*) FROM user_account
UNION ALL SELECT 'account',    COUNT(*) FROM account
UNION ALL SELECT 'instrument', COUNT(*) FROM instrument
UNION ALL SELECT 'bond',       COUNT(*) FROM bond
UNION ALL SELECT 'option',     COUNT(*) FROM option
UNION ALL SELECT 'price_bar',  COUNT(*) FROM price_bar
UNION ALL SELECT 'position',   COUNT(*) FROM position
UNION ALL SELECT 'cash_ledger',COUNT(*) FROM cash_ledger
ORDER BY tbl;

-- Check portfolio view:
SELECT account_id, symbol, qty, avg_cost, latest_close, market_value, unrealized_pnl
FROM portfolio_view
ORDER BY account_id, symbol;
*/

-- ===========================================================================
-- END OF SEED
-- ===========================================================================
