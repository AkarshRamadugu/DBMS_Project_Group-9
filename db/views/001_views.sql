-- =============================================================================
-- FILE: db/views/001_views.sql
-- PROJECT: Paper-Trading Exchange — Group 9, CS F212 Database Systems
-- DESCRIPTION:
--   Two database views:
--     1. order_book_view  — aggregated open/partial orders by instrument, side, price
--     2. portfolio_view   — positions with latest market price, market value, and P&L
-- PostgreSQL 16+   Run AFTER 001_schema.sql
-- =============================================================================


-- ===========================================================================
-- VIEW 1: order_book_view
--
-- Aggregates all OPEN and PARTIAL orders by (instrument_id, side, price).
-- Shows the number of orders at each price level and total available quantity.
-- For BUY side: sorted descending by price (highest bid first).
-- For SELL side: sorted ascending by price (lowest ask first).
--
-- Columns:
--   instrument_id  — the instrument being traded
--   symbol         — instrument ticker
--   side           — 'BUY' or 'SELL'
--   price          — the limit price level
--   order_count    — number of distinct orders at this level
--   total_qty      — total unfilled quantity at this level
--   sort_key       — derived sort column (use ORDER BY sort_key ASC in queries)
-- ===========================================================================

CREATE OR REPLACE VIEW order_book_view AS
WITH aggregated AS (
    SELECT
        o.instrument_id,
        i.symbol,
        o.side,
        o.price,
        COUNT(*)                        AS order_count,
        SUM(o.qty - o.filled_qty)       AS total_qty,
        -- Sort key: BUY side → negate price so highest bid = smallest key;
        --            SELL side → price ascending (lowest ask first)
        CASE
            WHEN o.side = 'BUY'  THEN -o.price
            WHEN o.side = 'SELL' THEN  o.price
        END                             AS sort_key
    FROM trade_order o
    JOIN instrument i ON i.instrument_id = o.instrument_id
    WHERE o.status IN ('OPEN', 'PARTIAL')
    GROUP BY o.instrument_id, i.symbol, o.side, o.price
)
SELECT
    instrument_id,
    symbol,
    side,
    price,
    order_count,
    total_qty,
    sort_key
FROM aggregated
ORDER BY instrument_id, side, sort_key ASC;

COMMENT ON VIEW order_book_view IS
    'Aggregated order book depth: open+partial orders grouped by (instrument, side, price).
     Sorted by price-time priority: BUY side highest-bid-first, SELL side lowest-ask-first.
     Use total_qty to render a depth-of-market widget.';


-- ===========================================================================
-- VIEW 2: portfolio_view
--
-- Joins POSITION with INSTRUMENT and the most recent PRICE_BAR per instrument
-- (using a LATERAL subquery to avoid a window-function + CTE overhead).
--
-- Computes per-position:
--   market_value     = qty × latest_close × multiplier
--   unrealized_pnl   = (latest_close − avg_cost) × qty × multiplier
--
-- Columns:
--   account_id, user_id, is_house
--   instrument_id, symbol, name, instrument_type, sector
--   qty, avg_cost
--   latest_close, latest_trade_date
--   multiplier
--   market_value
--   unrealized_pnl
-- ===========================================================================

CREATE OR REPLACE VIEW portfolio_view AS
SELECT
    p.account_id,
    a.user_id,
    a.is_house,
    p.instrument_id,
    i.symbol,
    i.name,
    i.instrument_type,
    i.sector,
    i.multiplier,
    p.qty,
    p.avg_cost,
    latest_pb.close            AS latest_close,
    latest_pb.trade_date       AS latest_trade_date,
    -- Market value: qty × most_recent_close × multiplier
    (p.qty * latest_pb.close * i.multiplier)
                               AS market_value,
    -- Unrealized P&L: (close − avg_cost) × qty × multiplier
    ((latest_pb.close - p.avg_cost) * p.qty * i.multiplier)
                               AS unrealized_pnl
FROM position p
JOIN account    a ON a.account_id    = p.account_id
JOIN instrument i ON i.instrument_id = p.instrument_id
-- LATERAL subquery: fetch the single most recent price_bar for each instrument
LEFT JOIN LATERAL (
    SELECT pb.close, pb.trade_date
    FROM price_bar pb
    WHERE pb.instrument_id = p.instrument_id
    ORDER BY pb.trade_date DESC
    LIMIT 1
) AS latest_pb ON TRUE
WHERE p.qty > 0;

COMMENT ON VIEW portfolio_view IS
    'Per-account, per-position snapshot with current market value and unrealized P&L.
     Uses a LATERAL subquery to efficiently retrieve the most recent price_bar close.
     market_value = qty × latest_close × multiplier.
     unrealized_pnl = (latest_close − avg_cost) × qty × multiplier.
     Only includes positions with qty > 0.';


-- ===========================================================================
-- BONUS VIEW: portfolio_summary_view
-- Rolls up portfolio_view to per-account totals including cash balance.
-- Useful for Workflow 2 (Portfolio Dashboard) from §2.1.
-- ===========================================================================

CREATE OR REPLACE VIEW portfolio_summary_view AS
SELECT
    pv.account_id,
    pv.user_id,
    pv.is_house,
    a.cash_balance,
    -- Aggregate by instrument type
    SUM(pv.market_value)   FILTER (WHERE pv.instrument_type = 'STOCK')  AS stock_market_value,
    SUM(pv.market_value)   FILTER (WHERE pv.instrument_type = 'BOND')   AS bond_market_value,
    SUM(pv.market_value)   FILTER (WHERE pv.instrument_type = 'OPTION') AS option_market_value,
    SUM(pv.market_value)                                                 AS total_holdings_value,
    SUM(pv.unrealized_pnl)                                               AS total_unrealized_pnl,
    -- Total portfolio value = cash + all holdings
    a.cash_balance + COALESCE(SUM(pv.market_value), 0)                  AS total_portfolio_value
FROM portfolio_view pv
JOIN account a ON a.account_id = pv.account_id
GROUP BY pv.account_id, pv.user_id, pv.is_house, a.cash_balance;

COMMENT ON VIEW portfolio_summary_view IS
    'Account-level portfolio summary: cash + holdings by asset class, total unrealized P&L, and total portfolio value.';


-- ===========================================================================
-- END OF VIEWS
-- ===========================================================================
