from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from app.database import get_conn

router = APIRouter()


@router.get("/order-book-depth/{instrument_id}")
async def order_book_depth(instrument_id: int):
    """
    Query 1: Order book depth with running total.
    Aggregates open orders by instrument, side, and price level,
    computing cumulative quantity using a window function (running sum).
    """
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT 1 FROM instrument WHERE instrument_id = %s",
                    (instrument_id,),
                )
                if await cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found")

                await cur.execute(
                    """
                    SELECT
                        side,
                        price,
                        SUM(qty - filled_qty)                                       AS level_qty,
                        COUNT(*)                                                     AS order_count,
                        SUM(SUM(qty - filled_qty)) OVER (
                            PARTITION BY side
                            ORDER BY
                                CASE WHEN side = 'BUY'  THEN price END DESC,
                                CASE WHEN side = 'SELL' THEN price END ASC
                        )                                                            AS cumulative_qty
                    FROM trade_order
                    WHERE instrument_id = %s
                      AND status IN ('OPEN', 'PARTIAL')
                    GROUP BY side, price
                    ORDER BY side DESC, price DESC
                    """,
                    (instrument_id,),
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/portfolio/{account_id}")
async def portfolio_value(account_id: int):
    """
    Query 2: Portfolio value with unrealized P&L.
    Uses a CTE + lateral join to get the latest close price per instrument,
    then computes market value and unrealized P&L per position.
    """
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT account_id, cash_balance FROM account WHERE account_id = %s",
                    (account_id,),
                )
                account = await cur.fetchone()
                if account is None:
                    raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

                await cur.execute(
                    """
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
                            lp.trade_date AS price_date,
                            (lp.latest_close * p.qty * i.multiplier)                       AS market_value,
                            ((lp.latest_close - p.avg_cost) * p.qty * i.multiplier)        AS unrealized_pnl
                        FROM position p
                        JOIN instrument i ON i.instrument_id = p.instrument_id
                        LEFT JOIN latest_prices lp ON lp.instrument_id = p.instrument_id
                        WHERE p.account_id = %s
                          AND p.qty > 0
                    )
                    SELECT
                        pv.*,
                        SUM(pv.market_value) OVER ()                              AS total_holdings_value,
                        %s::NUMERIC                                                AS cash_balance,
                        SUM(pv.market_value) OVER () + %s::NUMERIC                AS total_portfolio_value
                    FROM position_values pv
                    ORDER BY pv.symbol
                    """,
                    (account_id, account["cash_balance"], account["cash_balance"]),
                )
                rows = await cur.fetchall()
                return {
                    "account_id": account_id,
                    "cash_balance": float(account["cash_balance"]),
                    "positions": rows,
                }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/realized-pnl/{account_id}")
async def realized_pnl(account_id: int):
    """
    Query 3: Realized P&L per account.
    Joins trades with order_fills to separate buy proceeds from sell proceeds,
    aggregating profit and loss per instrument.
    """
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT 1 FROM account WHERE account_id = %s",
                    (account_id,),
                )
                if await cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

                await cur.execute(
                    """
                    SELECT
                        i.instrument_id,
                        i.symbol,
                        i.name,
                        i.instrument_type,
                        i.multiplier,
                        SUM(CASE WHEN o.side = 'BUY'  THEN -(t.price * of2.qty * i.multiplier) ELSE 0 END)  AS total_buy_cost,
                        SUM(CASE WHEN o.side = 'SELL' THEN  (t.price * of2.qty * i.multiplier) ELSE 0 END)  AS total_sell_proceeds,
                        SUM(CASE WHEN o.side = 'SELL' THEN  (t.price * of2.qty * i.multiplier) ELSE 0 END)
                        + SUM(CASE WHEN o.side = 'BUY' THEN -(t.price * of2.qty * i.multiplier) ELSE 0 END) AS realized_pnl,
                        SUM(of2.qty)                                                                          AS total_qty_traded,
                        COUNT(DISTINCT t.trade_id)                                                            AS trade_count
                    FROM order_fill of2
                    JOIN trade_order o  ON o.order_id  = of2.order_id
                    JOIN trade  t   ON t.trade_id  = of2.trade_id
                    JOIN instrument i ON i.instrument_id = o.instrument_id
                    WHERE o.account_id = %s
                    GROUP BY i.instrument_id, i.symbol, i.name, i.instrument_type, i.multiplier
                    ORDER BY realized_pnl DESC
                    """,
                    (account_id,),
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rolling-returns/{instrument_id}")
async def rolling_returns(instrument_id: int):
    """
    Query 4: Rolling 30-day return and max drawdown using LAG and MIN OVER window functions.
    Computes daily return vs 30 trading-days prior, and rolling max drawdown over a 30-day window.
    """
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT 1 FROM instrument WHERE instrument_id = %s",
                    (instrument_id,),
                )
                if await cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found")

                await cur.execute(
                    """
                    WITH daily AS (
                        SELECT
                            trade_date,
                            close,
                            LAG(close, 30) OVER (ORDER BY trade_date)  AS close_30d_ago,
                            MIN(close)     OVER (
                                ORDER BY trade_date
                                ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
                            )                                           AS rolling_30d_min,
                            MAX(close)     OVER (
                                ORDER BY trade_date
                                ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
                            )                                           AS rolling_30d_max
                        FROM price_bar
                        WHERE instrument_id = %s
                    )
                    SELECT
                        trade_date,
                        close,
                        close_30d_ago,
                        CASE
                            WHEN close_30d_ago IS NOT NULL AND close_30d_ago <> 0
                            THEN ROUND(((close - close_30d_ago) / close_30d_ago * 100)::NUMERIC, 4)
                        END                                             AS rolling_30d_return_pct,
                        rolling_30d_min,
                        rolling_30d_max,
                        CASE
                            WHEN rolling_30d_max IS NOT NULL AND rolling_30d_max <> 0
                            THEN ROUND(((rolling_30d_min - rolling_30d_max) / rolling_30d_max * 100)::NUMERIC, 4)
                        END                                             AS max_drawdown_pct
                    FROM daily
                    ORDER BY trade_date
                    """,
                    (instrument_id,),
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vwap/{instrument_id}")
async def vwap(instrument_id: int):
    """
    Query 5: VWAP (volume-weighted average price) per day.
    Computes VWAP using trade price and quantity from the trades table,
    grouped by trading day for the given instrument.
    """
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT 1 FROM instrument WHERE instrument_id = %s",
                    (instrument_id,),
                )
                if await cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found")

                await cur.execute(
                    """
                    SELECT
                        DATE(t.executed_at)                                        AS trade_date,
                        ROUND(
                            (SUM(t.price * t.qty) / NULLIF(SUM(t.qty), 0))::NUMERIC,
                            4
                        )                                                           AS vwap,
                        SUM(t.qty)                                                  AS total_volume,
                        COUNT(*)                                                    AS trade_count,
                        MIN(t.price)                                                AS low_price,
                        MAX(t.price)                                                AS high_price
                    FROM trade t
                    JOIN trade_order o ON o.order_id = t.buy_order_id
                    WHERE o.instrument_id = %s
                    GROUP BY DATE(t.executed_at)
                    ORDER BY trade_date
                    """,
                    (instrument_id,),
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/holdings-vs-cash")
async def holdings_vs_cash():
    """
    Query 6: Accounts where total holdings value exceeds cash balance.
    Uses a correlated subquery to compute total holdings value per account
    via the latest close prices, then filters to those exceeding cash balance.
    """
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
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
                    ORDER BY excess_over_cash DESC
                    """
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bond-ytm/{instrument_id}")
async def bond_ytm(instrument_id: int):
    """
    Query 7: Bond yield-to-maturity (YTM) approximation.
    Formula: YTM ≈ (coupon + (face_value - price) / years_to_maturity) / ((face_value + price) / 2)
    Uses the latest close price from price_bar as the current market price.
    """
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Verify it's a bond
                await cur.execute(
                    """
                    SELECT i.instrument_id, i.symbol, i.name, i.multiplier,
                           b.face_value, b.coupon_rate, b.coupon_frequency,
                           b.issue_date, b.maturity_date
                    FROM instrument i
                    JOIN bond b ON b.instrument_id = i.instrument_id
                    WHERE i.instrument_id = %s
                    """,
                    (instrument_id,),
                )
                bond = await cur.fetchone()
                if bond is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Instrument {instrument_id} not found or is not a BOND",
                    )

                # Get latest price
                await cur.execute(
                    """
                    SELECT close AS latest_price, trade_date
                    FROM price_bar
                    WHERE instrument_id = %s
                    ORDER BY trade_date DESC
                    LIMIT 1
                    """,
                    (instrument_id,),
                )
                price_row = await cur.fetchone()

                result = dict(bond)
                if price_row is None:
                    result["latest_price"] = None
                    result["market_price"] = None
                    result["price_date"] = None
                    result["years_to_maturity"] = None
                    result["annual_coupon"] = None
                    result["ytm_approx"] = None
                    result["ytm_pct"] = None
                    return result

                face_value = float(bond["face_value"])
                coupon_rate = float(bond["coupon_rate"])
                multiplier = float(bond["multiplier"])
                latest_price = float(price_row["latest_price"])
                market_price = latest_price * multiplier

                # Compute YTM using the approximation formula:
                # coupon_rate is stored as a decimal fraction (e.g. 0.0726 for 7.26%).
                # market_price scales clean quoted price by instrument.multiplier.
                await cur.execute(
                    """
                    SELECT
                        %s::NUMERIC                                                        AS latest_price,
                        %s::NUMERIC                                                        AS market_price,
                        %s::DATE                                                           AS price_date,
                        (%s::DATE - CURRENT_DATE) / 365.25                                 AS years_to_maturity,
                        (%s::NUMERIC * %s::NUMERIC)                                        AS annual_coupon,
                        CASE
                            WHEN (%s::DATE - CURRENT_DATE) > 0
                            THEN (
                                    (%s::NUMERIC * %s::NUMERIC)
                                    + ((%s::NUMERIC - %s::NUMERIC) / ((%s::DATE - CURRENT_DATE) / 365.25))
                                 ) / ((%s::NUMERIC + %s::NUMERIC) / 2.0)
                            ELSE NULL
                        END                                                                AS ytm_approx
                    """,
                    (
                        latest_price,
                        market_price,
                        price_row["trade_date"],
                        bond["maturity_date"],
                        face_value, coupon_rate,
                        bond["maturity_date"],
                        face_value, coupon_rate,
                        face_value, market_price,
                        bond["maturity_date"],
                        face_value, market_price,
                    ),
                )
                calc = await cur.fetchone()
                result.update(dict(price_row))
                result["latest_price"] = latest_price
                result["market_price"] = market_price
                result["price_date"] = calc["price_date"]
                result["years_to_maturity"] = round(float(calc["years_to_maturity"]), 4) if calc["years_to_maturity"] is not None else None
                result["annual_coupon"] = round(float(calc["annual_coupon"]), 2) if calc["annual_coupon"] is not None else None
                ytm = calc["ytm_approx"]
                result["ytm_approx"] = round(float(ytm), 6) if ytm is not None else None
                result["ytm_pct"] = round(float(ytm) * 100, 4) if ytm is not None else None
                return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
