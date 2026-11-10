-- =============================================================================
-- FILE: db/queries/001_analytical_queries.sql
-- PROJECT: Paper-Trading Exchange — Group 9, CS F212 Database Systems
-- DESCRIPTION:
--   Standalone versions of the 7 non-trivial analytical SQL queries (Spec §4).
--   These same queries are executed dynamically by the FastAPI endpoints in
--   backend/app/routers/analytics.py and visualized in the Streamlit UI.
--
-- HOW TO RUN MANUALLY:
--   psql -h localhost -U trader -d paper_trading -f db/queries/001_analytical_queries.sql
--   (or copy-paste individual queries into pgAdmin / DBeaver / psql)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- QUERY 1: Order Book Depth with Running Total (Endpoint: GET /analytics/order-book-depth/{instrument_id})
-- SQL concepts: GROUP BY, aggregate SUM/COUNT, Window Function SUM() OVER (PARTITION BY ... ORDER BY ...)
-- Example: instrument_id = 1 (RELIANCE)
-- -----------------------------------------------------------------------------
SELECT
    side,
    price,
    SUM(qty - filled_qty)                                       AS level_qty,
    COUNT(*)                                                    AS order_count,
    SUM(SUM(qty - filled_qty)) OVER (
        PARTITION BY side
        ORDER BY
            CASE WHEN side = 'BUY'  THEN price END DESC,
            CASE WHEN side = 'SELL' THEN price END ASC
    )                                                           AS cumulative_qty
FROM trade_order
WHERE instrument_id = 1
  AND status IN ('OPEN', 'PARTIAL')
GROUP BY side, price
ORDER BY side DESC, price DESC;


-- -----------------------------------------------------------------------------
-- QUERY 2: Portfolio Valuation & Unrealized P&L (Endpoint: GET /analytics/portfolio/{account_id})
-- SQL concepts: Multi-CTE, DISTINCT ON latest bar, multi-table JOIN, Window Function SUM() OVER ()
-- Example: account_id = 2 (Alice Trader)
-- -----------------------------------------------------------------------------
WITH latest_prices AS (
    SELECT DISTINCT ON (instrument_id)
        instrument_id,
        close AS latest_close,
        trade_date
    FROM price_bar
    ORDER BY instrument_id, trade_date DESC
),
position_values AS (
    SELECT
        p.account_id,
        p.instrument_id,
        i.symbol,
        i.name,
        i.instrument_type,
        i.multiplier,
        p.qty,
        p.avg_cost,
        lp.latest_close,
        lp.trade_date                                            AS price_date,
        (lp.latest_close * p.qty * i.multiplier)                 AS market_value,
        ((lp.latest_close - p.avg_cost) * p.qty * i.multiplier)  AS unrealized_pnl
    FROM position p
    JOIN instrument i     ON i.instrument_id = p.instrument_id
    LEFT JOIN latest_prices lp ON lp.instrument_id = p.instrument_id
    WHERE p.account_id = 2
      AND p.qty > 0
)
SELECT
    pv.*,
    SUM(pv.market_value) OVER ()                                 AS total_holdings_value,
    a.cash_balance,
    SUM(pv.market_value) OVER () + a.cash_balance                AS total_portfolio_value
FROM position_values pv
JOIN account a ON a.account_id = pv.account_id
ORDER BY pv.symbol;


-- -----------------------------------------------------------------------------
-- QUERY 3: Realized P&L per Account (Endpoint: GET /analytics/realized-pnl/{account_id})
-- SQL concepts: 4-table JOIN, conditional aggregation with CASE, COUNT(DISTINCT ...)
-- Example: account_id = 2 (Alice Trader)
-- -----------------------------------------------------------------------------
SELECT
    i.instrument_id,
    i.symbol,
    i.name,
    i.instrument_type,
    i.multiplier,
    SUM(CASE WHEN o.side = 'BUY'  THEN -(t.price * of2.qty * i.multiplier) ELSE 0 END) AS total_buy_cost,
    SUM(CASE WHEN o.side = 'SELL' THEN  (t.price * of2.qty * i.multiplier) ELSE 0 END) AS total_sell_proceeds,
    SUM(CASE WHEN o.side = 'SELL' THEN  (t.price * of2.qty * i.multiplier) ELSE 0 END)
    + SUM(CASE WHEN o.side = 'BUY' THEN -(t.price * of2.qty * i.multiplier) ELSE 0 END) AS realized_pnl,
    SUM(of2.qty)                                                                         AS total_qty_traded,
    COUNT(DISTINCT t.trade_id)                                                           AS trade_count
FROM order_fill of2
JOIN trade_order o  ON o.order_id  = of2.order_id
JOIN trade t        ON t.trade_id  = of2.trade_id
JOIN instrument i   ON i.instrument_id = o.instrument_id
WHERE o.account_id = 2
GROUP BY i.instrument_id, i.symbol, i.name, i.instrument_type, i.multiplier
ORDER BY realized_pnl DESC;


-- -----------------------------------------------------------------------------
-- QUERY 4: Rolling 30-Day Return & Max Drawdown (Endpoint: GET /analytics/rolling-returns/{instrument_id})
-- SQL concepts: CTE, Window Functions (LAG, MIN OVER, MAX OVER with ROWS BETWEEN frame)
-- Example: instrument_id = 1 (RELIANCE)
-- -----------------------------------------------------------------------------
WITH daily AS (
    SELECT
        trade_date,
        close,
        LAG(close, 30) OVER (ORDER BY trade_date) AS close_30d_ago,
        MIN(close)     OVER (
            ORDER BY trade_date
            ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        )                                         AS rolling_30d_min,
        MAX(close)     OVER (
            ORDER BY trade_date
            ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        )                                         AS rolling_30d_max
    FROM price_bar
    WHERE instrument_id = 1
)
SELECT
    trade_date,
    close,
    close_30d_ago,
    CASE
        WHEN close_30d_ago IS NOT NULL AND close_30d_ago <> 0
        THEN ROUND(((close - close_30d_ago) / close_30d_ago * 100)::NUMERIC, 4)
    END                                           AS rolling_30d_return_pct,
    rolling_30d_min,
    rolling_30d_max,
    CASE
        WHEN rolling_30d_max IS NOT NULL AND rolling_30d_max <> 0
        THEN ROUND(((rolling_30d_min - rolling_30d_max) / rolling_30d_max * 100)::NUMERIC, 4)
    END                                           AS max_drawdown_pct
FROM daily
ORDER BY trade_date;


-- -----------------------------------------------------------------------------
-- QUERY 5: Volume-Weighted Average Price (VWAP) per Day (Endpoint: GET /analytics/vwap/{instrument_id})
-- SQL concepts: Multi-table JOIN, weighted average SUM(p*q)/SUM(q), NULLIF guard, GROUP BY day
-- Example: instrument_id = 1 (RELIANCE)
-- -----------------------------------------------------------------------------
SELECT
    DATE(t.executed_at)                                        AS trade_date,
    ROUND(
        (SUM(t.price * t.qty) / NULLIF(SUM(t.qty), 0))::NUMERIC,
        4
    )                                                          AS vwap,
    SUM(t.qty)                                                 AS total_volume,
    COUNT(*)                                                   AS trade_count,
    MIN(t.price)                                               AS low_price,
    MAX(t.price)                                               AS high_price
FROM trade t
JOIN trade_order o ON o.order_id = t.buy_order_id
WHERE o.instrument_id = 1
GROUP BY DATE(t.executed_at)
ORDER BY trade_date;


-- -----------------------------------------------------------------------------
-- QUERY 6: Accounts Where Holdings Value Exceeds Cash Balance (Endpoint: GET /analytics/holdings-vs-cash)
-- SQL concepts: LATERAL join + correlated scalar subquery for latest price, COALESCE
-- -----------------------------------------------------------------------------
SELECT
    a.account_id,
    u.name        AS user_name,
    u.email       AS user_email,
    a.cash_balance,
    holdings.total_holdings_value,
    ROUND((holdings.total_holdings_value - a.cash_balance)::NUMERIC, 2) AS excess_over_cash
FROM account a
JOIN user_account u ON u.user_id = a.user_id
JOIN LATERAL (
    SELECT
        COALESCE(
            SUM(
                p.qty
                * i.multiplier
                * (
                    SELECT pb.close
                    FROM price_bar pb
                    WHERE pb.instrument_id = p.instrument_id
                    ORDER BY pb.trade_date DESC
                    LIMIT 1
                )
            ),
            0
        ) AS total_holdings_value
    FROM position p
    JOIN instrument i ON i.instrument_id = p.instrument_id
    WHERE p.account_id = a.account_id
      AND p.qty > 0
) holdings ON TRUE
WHERE a.is_house = FALSE
  AND holdings.total_holdings_value > a.cash_balance
ORDER BY excess_over_cash DESC;


-- -----------------------------------------------------------------------------
-- QUERY 7: Bond Yield-to-Maturity (YTM) Approximation (Endpoint: GET /analytics/bond-ytm/{instrument_id})
-- SQL concepts: Subtype JOIN (instrument ⋈ bond), LATERAL latest price, financial date/math expression
-- Formula: YTM ≈ (annual_coupon + (face_value - market_price) / years_to_maturity)
--                / ((face_value + market_price) / 2)
-- -----------------------------------------------------------------------------
SELECT
    i.instrument_id,
    i.symbol,
    i.name,
    b.face_value,
    b.coupon_rate,
    b.maturity_date,
    pb.close                                                           AS latest_clean_price,
    (pb.close * i.multiplier)                                          AS market_price,
    ROUND(((b.maturity_date - CURRENT_DATE) / 365.25)::NUMERIC, 4)     AS years_to_maturity,
    ROUND((b.face_value * b.coupon_rate)::NUMERIC, 2)                  AS annual_coupon,
    ROUND((
        (
            (b.face_value * b.coupon_rate)
            + ((b.face_value - (pb.close * i.multiplier)) / ((b.maturity_date - CURRENT_DATE) / 365.25))
        ) / ((b.face_value + (pb.close * i.multiplier)) / 2.0)
        * 100
    )::NUMERIC, 4)                                                     AS ytm_pct
FROM instrument i
JOIN bond b ON b.instrument_id = i.instrument_id
JOIN LATERAL (
    SELECT close
    FROM price_bar
    WHERE instrument_id = i.instrument_id
    ORDER BY trade_date DESC
    LIMIT 1
) pb ON TRUE
WHERE i.instrument_type = 'BOND'
  AND b.maturity_date > CURRENT_DATE
ORDER BY i.symbol;

