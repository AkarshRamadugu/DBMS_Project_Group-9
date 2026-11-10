import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
import psycopg
from pydantic import BaseModel, Field, field_validator
from psycopg.rows import dict_row

from app.database import get_conn

router = APIRouter()


class PlaceOrderBody(BaseModel):
    account_id: int = Field(..., gt=0)
    instrument_id: int = Field(..., gt=0)
    side: str = Field(..., description="BUY or SELL")
    price: float = Field(..., gt=0)
    qty: int = Field(..., gt=0)

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        v = v.upper()
        if v not in ("BUY", "SELL"):
            raise ValueError("side must be 'BUY' or 'SELL'")
        return v


@router.get("")
async def list_orders(
    account_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None, description="OPEN, PARTIAL, FILLED, CANCELLED"),
):
    """List orders with optional account_id and status filters."""
    valid_statuses = {"OPEN", "PARTIAL", "FILLED", "CANCELLED"}
    if status is not None and status.upper() not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}")

    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                conditions = []
                params = []

                if account_id is not None:
                    conditions.append("o.account_id = %s")
                    params.append(account_id)
                if status is not None:
                    conditions.append("o.status = %s")
                    params.append(status.upper())

                where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

                await cur.execute(
                    f"""
                    SELECT o.order_id, o.account_id, o.instrument_id, o.side,
                           o.price, o.qty, o.filled_qty, o.status, o.created_at,
                           i.symbol AS instrument_symbol
                    FROM trade_order o
                    JOIN instrument i ON i.instrument_id = o.instrument_id
                    {where_clause}
                    ORDER BY o.created_at DESC
                    """,
                    params,
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{order_id}")
async def get_order(order_id: int):
    """Get order detail including fills."""
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT o.order_id, o.account_id, o.instrument_id, o.side,
                           o.price, o.qty, o.filled_qty, o.status, o.created_at,
                           i.symbol AS instrument_symbol
                    FROM trade_order o
                    JOIN instrument i ON i.instrument_id = o.instrument_id
                    WHERE o.order_id = %s
                    """,
                    (order_id,),
                )
                order = await cur.fetchone()
                if order is None:
                    raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

                await cur.execute(
                    """
                    SELECT fill_seq, trade_id, qty, price, filled_at
                    FROM order_fill
                    WHERE order_id = %s
                    ORDER BY fill_seq
                    """,
                    (order_id,),
                )
                fills = await cur.fetchall()

                result = dict(order)
                result["fills"] = [dict(f) for f in fills]
                return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", status_code=201)
async def place_order(body: PlaceOrderBody):
    """Place a new limit order and attempt matching via match_and_settle stored procedure."""
    max_retries = 3
    try:
        async with get_conn() as conn:
            for attempt in range(max_retries):
                try:
                    async with conn.transaction():
                        async with conn.cursor(row_factory=dict_row) as cur:
                            # Must be the first statement in the transaction
                            await cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")

                            # Validate account exists
                            await cur.execute(
                                "SELECT account_id, cash_balance FROM account WHERE account_id = %s",
                                (body.account_id,),
                            )
                            account = await cur.fetchone()
                            if account is None:
                                raise HTTPException(status_code=404, detail=f"Account {body.account_id} not found")

                            # Validate instrument exists and is active
                            await cur.execute(
                                "SELECT instrument_id, status, multiplier FROM instrument WHERE instrument_id = %s",
                                (body.instrument_id,),
                            )
                            instrument = await cur.fetchone()
                            if instrument is None:
                                raise HTTPException(status_code=404, detail=f"Instrument {body.instrument_id} not found")
                            if instrument["status"] == "EXPIRED":
                                raise HTTPException(status_code=400, detail="Cannot place order on an EXPIRED instrument")
                            if instrument["status"] == "HALTED":
                                raise HTTPException(status_code=400, detail="Cannot place order on a HALTED instrument")

                            # Pre-check cash for BUY orders (match_and_settle enforces again under lock)
                            if body.side == "BUY":
                                cost = body.price * body.qty * float(instrument["multiplier"])
                                if float(account["cash_balance"]) < cost:
                                    raise HTTPException(
                                        status_code=400,
                                        detail=(
                                            f"Insufficient cash. Required: {cost:.2f}, "
                                            f"Available: {float(account['cash_balance']):.2f}"
                                        ),
                                    )

                            await cur.execute(
                                """
                                INSERT INTO trade_order (account_id, instrument_id, side, price, qty, filled_qty, status)
                                VALUES (%s, %s, %s, %s, %s, 0, 'OPEN')
                                RETURNING order_id
                                """,
                                (body.account_id, body.instrument_id, body.side, body.price, body.qty),
                            )
                            order_row = await cur.fetchone()
                            order_id = order_row["order_id"]

                            # Execute matching engine stored procedure in the same SERIALIZABLE transaction
                            await cur.execute("CALL match_and_settle(%s)", (order_id,))

                            # Re-fetch updated order and any fills
                            await cur.execute(
                                """
                                SELECT o.order_id, o.account_id, o.instrument_id, o.side,
                                       o.price, o.qty, o.filled_qty, o.status, o.created_at,
                                       i.symbol AS instrument_symbol
                                FROM trade_order o
                                JOIN instrument i ON i.instrument_id = o.instrument_id
                                WHERE o.order_id = %s
                                """,
                                (order_id,),
                            )
                            updated_order = await cur.fetchone()

                            await cur.execute(
                                """
                                SELECT fill_seq, trade_id, qty, price, filled_at
                                FROM order_fill
                                WHERE order_id = %s
                                ORDER BY fill_seq
                                """,
                                (order_id,),
                            )
                            fills = await cur.fetchall()

                    result = dict(updated_order)
                    result["fills"] = [dict(f) for f in fills]
                    return result

                except psycopg.errors.SerializationFailure:
                    if attempt == max_retries - 1:
                        raise HTTPException(
                            status_code=409,
                            detail="Concurrent serialization conflict; please retry order.",
                        )
                    await asyncio.sleep(0.05 * (2 ** attempt))
                except (
                    psycopg.errors.RaiseException,
                    psycopg.errors.IntegrityError,
                ) as db_err:
                    msg = db_err.diag.message_primary or str(db_err)
                    raise HTTPException(status_code=400, detail=msg)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{order_id}", status_code=200)
async def cancel_order(order_id: int):
    """Cancel an OPEN or PARTIAL order."""
    try:
        async with get_conn() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "SELECT order_id, status FROM trade_order WHERE order_id = %s FOR UPDATE",
                        (order_id,),
                    )
                    order = await cur.fetchone()
                    if order is None:
                        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
                    if order["status"] not in ("OPEN", "PARTIAL"):
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"Cannot cancel order with status '{order['status']}'. "
                                "Only OPEN or PARTIAL orders can be cancelled."
                            ),
                        )

                    await cur.execute(
                        """
                        UPDATE trade_order
                        SET status = 'CANCELLED'
                        WHERE order_id = %s
                        RETURNING order_id, account_id, instrument_id, side, price, qty, filled_qty, status, created_at
                        """,
                        (order_id,),
                    )
                    updated = await cur.fetchone()
                    return dict(updated)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
