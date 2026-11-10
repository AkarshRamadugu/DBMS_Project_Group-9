"""
scripts/run_stress_test.py
==========================
Concurrency stress test for the Paper-Trading Exchange API.

Workflow
--------
1. Spin up 10 threads; each places random BUY/SELL orders via POST /orders.
2. After all threads finish, connect to PostgreSQL and verify three invariants:
   a) CASH_LEDGER consistency:
      SUM(amount) per account_id equals account.cash_balance
   b) ORDER_FILL consistency:
      SUM(order_fill.qty) per order_id equals order.filled_qty
   c) No negative positions:
      All position.qty >= 0

Usage
-----
    python scripts/run_stress_test.py

Environment variables:
    API_URL           default: http://localhost:8000
    POSTGRES_HOST     default: localhost
    POSTGRES_PORT     default: 5432
    POSTGRES_DB       default: paper_trading
    POSTGRES_USER     default: trader
    POSTGRES_PASSWORD default: changeme
    NUM_THREADS       default: 10
    ORDERS_PER_THREAD default: 20
"""

import os
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL = os.environ.get("API_URL", "http://localhost:8000")
NUM_THREADS = int(os.environ.get("NUM_THREADS", "10"))
ORDERS_PER_THREAD = int(os.environ.get("ORDERS_PER_THREAD", "20"))

DSN = (
    "host={host} port={port} dbname={db} user={user} password={password}".format(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        db=os.environ.get("POSTGRES_DB", "paper_trading"),
        user=os.environ.get("POSTGRES_USER", "trader"),
        password=os.environ.get("POSTGRES_PASSWORD", "changeme"),
    )
)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
@dataclass
class Stats:
    orders_placed: int = 0
    orders_failed: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record_success(self):
        with self.lock:
            self.orders_placed += 1

    def record_failure(self):
        with self.lock:
            self.orders_failed += 1


stats = Stats()


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def api_get(path: str) -> Any:
    resp = requests.get(f"{API_URL}{path}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, payload: dict) -> Any:
    resp = requests.post(f"{API_URL}{path}", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Fetch seed data
# ---------------------------------------------------------------------------
def fetch_accounts_and_instruments():
    accounts = api_get("/accounts")
    instruments = api_get("/instruments")
    # Filter out the house account (is_house=True) for safety
    trader_accounts = [a for a in accounts if not a.get("is_house", False)]
    if not trader_accounts:
        trader_accounts = accounts          # fall back if no non-house account
    active_instruments = [
        i for i in instruments
        if str(i.get("status", "ACTIVE")).upper() == "ACTIVE"
    ]
    return trader_accounts, active_instruments


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------
def worker(thread_id: int, accounts: list[dict], instruments: list[dict]):
    """Place ORDERS_PER_THREAD random limit orders."""
    rng = random.Random(thread_id * 9973 + int(time.time()))

    for _ in range(ORDERS_PER_THREAD):
        account = rng.choice(accounts)
        instrument = rng.choice(instruments)

        # Pick a plausible price near last known close (or a fixed range)
        base_price = float(instrument.get("tick_size", 1)) * rng.randint(500, 5000)
        price = round(max(0.05, base_price), 2)
        qty = rng.randint(1, 10)
        side = rng.choice(["BUY", "SELL"])

        payload = {
            "account_id":    account["account_id"],
            "instrument_id": instrument["instrument_id"],
            "side":          side,
            "price":         price,
            "qty":           qty,
        }

        try:
            api_post("/orders", payload)
            stats.record_success()
        except requests.exceptions.HTTPError as exc:
            # 400/422 are expected (insufficient cash, constraint violation, etc.)
            stats.record_failure()
        except Exception as exc:
            print(f"  [thread-{thread_id}] Unexpected error: {exc}", file=sys.stderr)
            stats.record_failure()

        # Small jitter to increase contention
        time.sleep(rng.uniform(0.0, 0.05))


# ---------------------------------------------------------------------------
# Invariant checks (run against the DB directly)
# ---------------------------------------------------------------------------
def check_invariants(conn) -> dict[str, bool]:
    results: dict[str, bool] = {}

    with conn.cursor() as cur:
        # ------------------------------------------------------------------
        # Invariant 1 — CASH_LEDGER sum == account.cash_balance
        # ------------------------------------------------------------------
        cur.execute(
            """
            SELECT
                a.account_id,
                a.cash_balance                   AS stored_balance,
                COALESCE(SUM(cl.amount), 0)      AS ledger_sum
            FROM   account a
            LEFT JOIN cash_ledger cl
                   ON cl.account_id = a.account_id
            GROUP BY a.account_id, a.cash_balance
            HAVING ABS(a.cash_balance - COALESCE(SUM(cl.amount), 0)) > 0.01;
            """
        )
        mismatches = cur.fetchall()
        if mismatches:
            print("  [FAIL] Cash-ledger mismatches:")
            for m in mismatches:
                print(f"    account_id={m[0]}  stored={m[1]}  ledger_sum={m[2]}")
            results["cash_ledger_consistency"] = False
        else:
            results["cash_ledger_consistency"] = True

        # ------------------------------------------------------------------
        # Invariant 2 — SUM(order_fill.qty) == order.filled_qty
        # ------------------------------------------------------------------
        cur.execute(
            """
            SELECT
                o.order_id,
                o.filled_qty                       AS stored_filled_qty,
                COALESCE(SUM(of2.qty), 0)          AS fill_sum
            FROM   trade_order o
            LEFT JOIN order_fill of2
                   ON of2.order_id = o.order_id
            GROUP BY o.order_id, o.filled_qty
            HAVING ABS(o.filled_qty - COALESCE(SUM(of2.qty), 0)) > 0;
            """
        )
        fill_mismatches = cur.fetchall()
        if fill_mismatches:
            print("  [FAIL] Order-fill mismatches:")
            for m in fill_mismatches:
                print(f"    order_id={m[0]}  stored={m[1]}  fill_sum={m[2]}")
            results["order_fill_consistency"] = False
        else:
            results["order_fill_consistency"] = True

        # ------------------------------------------------------------------
        # Invariant 3 — No position with qty < 0
        # ------------------------------------------------------------------
        cur.execute(
            """
            SELECT account_id, instrument_id, qty
            FROM   position
            WHERE  qty < 0;
            """
        )
        negative_positions = cur.fetchall()
        if negative_positions:
            print("  [FAIL] Negative positions found:")
            for p in negative_positions:
                print(f"    account_id={p[0]}  instrument_id={p[1]}  qty={p[2]}")
            results["no_negative_positions"] = False
        else:
            results["no_negative_positions"] = True

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Paper-Trading Exchange — Concurrency Stress Test")
    print("=" * 60)
    print(f"Threads: {NUM_THREADS}  |  Orders per thread: {ORDERS_PER_THREAD}")
    print(f"API URL: {API_URL}")
    print()

    # Fetch accounts and instruments once
    print("Fetching accounts and instruments …")
    try:
        accounts, instruments = fetch_accounts_and_instruments()
    except Exception as exc:
        print(f"ERROR: Could not reach API — {exc}")
        sys.exit(1)

    if not accounts:
        print("ERROR: No accounts found. Seed the database first.")
        sys.exit(1)
    if not instruments:
        print("ERROR: No active instruments found. Seed the database first.")
        sys.exit(1)

    print(f"  {len(accounts)} account(s), {len(instruments)} active instrument(s)")
    print()

    # Launch worker threads
    print(f"Starting {NUM_THREADS} worker threads …")
    t0 = time.monotonic()
    threads = []
    for tid in range(NUM_THREADS):
        t = threading.Thread(
            target=worker,
            args=(tid, accounts, instruments),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    elapsed = time.monotonic() - t0
    total_attempted = NUM_THREADS * ORDERS_PER_THREAD
    print(
        f"Done in {elapsed:.1f}s — "
        f"{stats.orders_placed}/{total_attempted} orders placed, "
        f"{stats.orders_failed} failed (expected for constraint violations)."
    )
    print()

    # Verify invariants
    print("Verifying database invariants …")
    try:
        with psycopg.connect(DSN, autocommit=True) as conn:
            results = check_invariants(conn)
    except Exception as exc:
        print(f"ERROR: Could not connect to database — {exc}")
        sys.exit(1)

    print()
    print("-" * 40)
    all_passed = True
    for invariant, passed in results.items():
        label = "PASS ✓" if passed else "FAIL ✗"
        print(f"  [{label}]  {invariant}")
        if not passed:
            all_passed = False

    print("-" * 40)
    if all_passed:
        print("All invariants passed. ✓")
        sys.exit(0)
    else:
        print("One or more invariants FAILED. ✗")
        sys.exit(1)


if __name__ == "__main__":
    main()
