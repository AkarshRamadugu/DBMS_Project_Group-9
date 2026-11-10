from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from app.database import get_conn

router = APIRouter()


@router.get("")
async def list_instruments(
    type: Optional[str] = Query(default=None, description="Filter by instrument type: STOCK, BOND, OPTION"),
):
    """List all instruments with optional type filter."""
    valid_types = {"STOCK", "BOND", "OPTION"}
    if type is not None and type.upper() not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid type. Must be one of: {', '.join(valid_types)}")

    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                if type is not None:
                    await cur.execute(
                        """
                        SELECT instrument_id, symbol, name, instrument_type, sector,
                               multiplier, tick_size, lot_size, status
                        FROM instrument
                        WHERE instrument_type = %s
                        ORDER BY symbol
                        """,
                        (type.upper(),),
                    )
                else:
                    await cur.execute(
                        """
                        SELECT instrument_id, symbol, name, instrument_type, sector,
                               multiplier, tick_size, lot_size, status
                        FROM instrument
                        ORDER BY symbol
                        """
                    )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{instrument_id}")
async def get_instrument(instrument_id: int):
    """Get instrument detail; for BOND join bond table, for OPTION join option table."""
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Fetch base instrument
                await cur.execute(
                    """
                    SELECT instrument_id, symbol, name, instrument_type, sector,
                           multiplier, tick_size, lot_size, status
                    FROM instrument
                    WHERE instrument_id = %s
                    """,
                    (instrument_id,),
                )
                instrument = await cur.fetchone()
                if instrument is None:
                    raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found")

                result = dict(instrument)

                # Join subtype table if applicable
                if result["instrument_type"] == "BOND":
                    await cur.execute(
                        """
                        SELECT face_value, coupon_rate, coupon_frequency,
                               issue_date, maturity_date
                        FROM bond
                        WHERE instrument_id = %s
                        """,
                        (instrument_id,),
                    )
                    bond_data = await cur.fetchone()
                    if bond_data:
                        result.update(dict(bond_data))

                elif result["instrument_type"] == "OPTION":
                    await cur.execute(
                        """
                        SELECT o.underlying_id, o.strike, o.expiry, o.option_type,
                               i.symbol AS underlying_symbol
                        FROM option o
                        JOIN instrument i ON i.instrument_id = o.underlying_id
                        WHERE o.instrument_id = %s
                        """,
                        (instrument_id,),
                    )
                    option_data = await cur.fetchone()
                    if option_data:
                        result.update(dict(option_data))

                return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{instrument_id}/price-bars")
async def get_price_bars(
    instrument_id: int,
    days: int = Query(default=252, ge=1, le=1000, description="Number of most recent trading bars to fetch"),
):
    """Get OHLCV price bars for an instrument."""
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Verify instrument exists
                await cur.execute(
                    "SELECT 1 FROM instrument WHERE instrument_id = %s",
                    (instrument_id,),
                )
                if await cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found")

                await cur.execute(
                    """
                    SELECT trade_date, open, high, low, close, volume
                    FROM (
                        SELECT trade_date, open, high, low, close, volume
                        FROM price_bar
                        WHERE instrument_id = %s
                        ORDER BY trade_date DESC
                        LIMIT %s
                    ) recent
                    ORDER BY trade_date ASC
                    """,
                    (instrument_id, days),
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{instrument_id}/order-book")
async def get_order_book(instrument_id: int):
    """Get the order book view for a specific instrument."""
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Verify instrument exists
                await cur.execute(
                    "SELECT 1 FROM instrument WHERE instrument_id = %s",
                    (instrument_id,),
                )
                if await cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found")

                await cur.execute(
                    """
                    SELECT *
                    FROM order_book_view
                    WHERE instrument_id = %s
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
