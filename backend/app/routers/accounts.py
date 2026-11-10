from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from app.database import get_conn

router = APIRouter()


class DepositBody(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to deposit (must be positive)")


@router.get("")
async def list_accounts():
    """List all non-house accounts."""
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT a.account_id, a.user_id, a.cash_balance, a.is_house, a.created_at,
                           u.name AS user_name, u.email AS user_email
                    FROM account a
                    JOIN user_account u ON u.user_id = a.user_id
                    WHERE a.is_house = FALSE
                    ORDER BY a.account_id
                    """
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{account_id}")
async def get_account(account_id: int):
    """Get account detail including cash_balance."""
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT a.account_id, a.user_id, a.cash_balance, a.is_house, a.created_at,
                           u.name AS user_name, u.email AS user_email
                    FROM account a
                    JOIN user_account u ON u.user_id = a.user_id
                    WHERE a.account_id = %s
                    """,
                    (account_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
                return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{account_id}/positions")
async def get_positions(account_id: int):
    """Get portfolio view for this account."""
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Verify account exists
                await cur.execute(
                    "SELECT 1 FROM account WHERE account_id = %s",
                    (account_id,),
                )
                if await cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

                await cur.execute(
                    """
                    SELECT *
                    FROM portfolio_view
                    WHERE account_id = %s
                    ORDER BY symbol
                    """,
                    (account_id,),
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{account_id}/ledger")
async def get_ledger(
    account_id: int,
    limit: int = Query(default=50, ge=1, le=500, description="Max number of entries to return"),
):
    """Get recent cash_ledger entries for an account."""
    try:
        async with get_conn() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Verify account exists
                await cur.execute(
                    "SELECT 1 FROM account WHERE account_id = %s",
                    (account_id,),
                )
                if await cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

                await cur.execute(
                    """
                    SELECT cl.ledger_id, cl.account_id, cl.trade_id, cl.instrument_id,
                           cl.entry_type, cl.amount, cl.value_date, cl.created_at,
                           i.symbol AS instrument_symbol
                    FROM cash_ledger cl
                    LEFT JOIN instrument i ON i.instrument_id = cl.instrument_id
                    WHERE cl.account_id = %s
                    ORDER BY cl.created_at DESC
                    LIMIT %s
                    """,
                    (account_id, limit),
                )
                rows = await cur.fetchall()
                return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{account_id}/deposit")
async def deposit(account_id: int, body: DepositBody):
    """Insert a DEPOSIT cash_ledger entry and update cash_balance in a transaction."""
    try:
        async with get_conn() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    # Lock account row and verify it exists
                    await cur.execute(
                        "SELECT account_id, cash_balance FROM account WHERE account_id = %s FOR UPDATE",
                        (account_id,),
                    )
                    account = await cur.fetchone()
                    if account is None:
                        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

                    # Insert DEPOSIT ledger entry (nullable instrument_id allows repeated same-day deposits)
                    await cur.execute(
                        """
                        INSERT INTO cash_ledger (account_id, trade_id, instrument_id, entry_type, amount, value_date)
                        VALUES (%s, NULL, NULL, 'DEPOSIT', %s, CURRENT_DATE)
                        RETURNING ledger_id, account_id, entry_type, amount, value_date, created_at
                        """,
                        (account_id, body.amount),
                    )
                    ledger_entry = await cur.fetchone()

                    # Update cash_balance
                    await cur.execute(
                        """
                        UPDATE account
                        SET cash_balance = cash_balance + %s
                        WHERE account_id = %s
                        RETURNING cash_balance
                        """,
                        (body.amount, account_id),
                    )
                    updated = await cur.fetchone()

            return {
                "ledger_entry": dict(ledger_entry),
                "new_cash_balance": updated["cash_balance"],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
