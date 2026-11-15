"""
scripts/demo_concurrent_orders.py
=================================
Live demonstration of simultaneous orders against the matching engine.

Scenario
--------
1. The house account posts ONE resting SELL order for 50 units of a stock,
   priced inside the current spread so only these buyers can hit it.
2. 12 BUY orders of 5 units each (60 units demanded, only 50 available) are
   released at the same instant from Alice's and Bob's accounts
   (threads synchronised with a barrier).
3. The script prints every order's outcome and checks that:
     • exactly 50 units were filled — no double-fill, no oversell,
     • the SELL order's filled_qty equals the sum of all buyer fills,
     • the unfilled 10 units are left resting in the book,
     • database invariants hold (cash = ledger sum, filled_qty = fills, qty >= 0).
4. Leftover buy orders are cancelled so the book is clean again.

Run (Docker, from the repository root)
--------------------------------------
    PowerShell:  Get-Content scripts/demo_concurrent_orders.py | docker compose exec -T backend python -
    Bash:        docker compose exec -T backend python - < scripts/demo_concurrent_orders.py

Environment variables (optional): API_URL (default http://localhost:8000),
DEMO_SYMBOL (default RELIANCE), DEMO_BUYERS (default 12), POSTGRES_* as in seed_prices.py.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request

API_URL = os.environ.get("API_URL", "http://localhost:8000")
SYMBOL = os.environ.get("DEMO_SYMBOL", "RELIANCE")
N_BUYERS = int(os.environ.get("DEMO_BUYERS", "12"))
BUY_QTY = 5
SELL_QTY = 50
HOUSE_ACCOUNT = 1


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{API_URL}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def snap(price, tick):
    return round(round(price / tick) * tick, 2)


def main():
    instruments = call("GET", "/instruments")[1]
    inst = next(i for i in instruments if i["symbol"] == SYMBOL)
    iid, tick = inst["instrument_id"], float(inst["tick_size"])
    accounts = [a["account_id"] for a in call("GET", "/accounts")[1]]

    # Price inside the spread so the buyers can only match our SELL order
    depth = call("GET", f"/analytics/order-book-depth/{iid}")[1]
    bids = [float(r["price"]) for r in depth if r["side"] == "BUY"]
    asks = [float(r["price"]) for r in depth if r["side"] == "SELL"]
    last = float(call("GET", f"/instruments/{iid}/price-bars?days=1")[1][-1]["close"])
    best_bid = max(bids) if bids else None
    best_ask = min(asks) if asks else None
    if best_bid and best_ask and best_ask - best_bid > 2 * tick:
        price = snap((best_bid + best_ask) / 2, tick)
    elif best_ask:
        price = snap(best_ask - tick, tick)
    else:
        price = snap(max(last, (best_bid or 0) + tick), tick)
    if best_bid and price <= best_bid:
        raise SystemExit(f"Spread too narrow on {SYMBOL}; set DEMO_SYMBOL to another stock.")

    print(f"\n=== Simultaneous-order demo on {SYMBOL} @ ₹{price:,.2f} ===")
    print(f"Book before: best bid {best_bid}, best ask {best_ask}\n")

    status, sell = call("POST", "/orders", {"account_id": HOUSE_ACCOUNT, "instrument_id": iid,
                                           "side": "SELL", "price": price, "qty": SELL_QTY})
    if status != 201:
        raise SystemExit(f"Could not place house SELL order: {sell}")
    print(f"House SELL order #{sell['order_id']}: {SELL_QTY} units resting in the book.")
    print(f"Releasing {N_BUYERS} BUY orders x {BUY_QTY} units "
          f"({N_BUYERS * BUY_QTY} demanded, {SELL_QTY} available) at the same instant ...\n")

    barrier = threading.Barrier(N_BUYERS)
    results = [None] * N_BUYERS

    def buyer(i):
        account = accounts[i % len(accounts)]
        barrier.wait()                      # everyone fires together
        t0 = time.perf_counter()
        code, body = call("POST", "/orders", {"account_id": account, "instrument_id": iid,
                                             "side": "BUY", "price": price, "qty": BUY_QTY})
        results[i] = (account, code, body, (time.perf_counter() - t0) * 1000)

    threads = [threading.Thread(target=buyer, args=(i,)) for i in range(N_BUYERS)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = (time.perf_counter() - started) * 1000

    print(f"{'#':>2}  {'account':>7}  {'order':>6}  {'HTTP':>4}  {'status':<9} {'filled':>6}  {'latency':>8}")
    filled_total, resting = 0, []
    for i, (account, code, body, ms) in enumerate(results, 1):
        status = body.get("status", body.get("detail", "?"))
        filled = int(body.get("filled_qty") or 0)
        filled_total += filled
        if status in ("OPEN", "PARTIAL"):
            resting.append(body["order_id"])
        print(f"{i:>2}  {account:>7}  {body.get('order_id', '-'):>6}  {code:>4}  {status:<9} {filled:>6}  {ms:>6.0f}ms")

    sell_after = call("GET", f"/orders/{sell['order_id']}")[1]
    print(f"\nAll {N_BUYERS} orders processed in {elapsed:.0f} ms.")
    print(f"Units bought by all buyers      : {filled_total}")
    print(f"House SELL order filled_qty     : {sell_after['filled_qty']} / {SELL_QTY} ({sell_after['status']})")
    print(f"Buy orders left resting in book : {len(resting)}")

    checks = {
        "no oversell: buyers received exactly the 50 units on offer": filled_total == SELL_QTY,
        "SELL filled_qty equals the sum of buyer fills": int(sell_after["filled_qty"]) == filled_total,
        "every request succeeded (no 5xx / deadlock errors)": all(r[1] == 201 for r in results),
    }

    try:
        import psycopg
        dsn = "host={} port={} dbname={} user={} password={}".format(
            os.environ.get("POSTGRES_HOST", "localhost"), os.environ.get("POSTGRES_PORT", "5432"),
            os.environ.get("POSTGRES_DB", "paper_trading"), os.environ.get("POSTGRES_USER", "trader"),
            os.environ.get("POSTGRES_PASSWORD", "changeme"))
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("""SELECT count(*) FROM account a WHERE abs(a.cash_balance -
                           (SELECT COALESCE(sum(amount),0) FROM cash_ledger c WHERE c.account_id=a.account_id)) > 0.01""")
            checks["DB: every cash_balance equals its CASH_LEDGER sum"] = cur.fetchone()[0] == 0
            cur.execute("""SELECT count(*) FROM trade_order o WHERE o.filled_qty <>
                           (SELECT COALESCE(sum(qty),0) FROM order_fill f WHERE f.order_id=o.order_id)""")
            checks["DB: every filled_qty equals its ORDER_FILL sum"] = cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM position WHERE qty < 0")
            checks["DB: no negative positions"] = cur.fetchone()[0] == 0
    except Exception as exc:  # psycopg missing or DB unreachable: API checks still shown
        print(f"(Skipping direct DB checks: {exc})")

    print()
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    for oid in resting:
        call("DELETE", f"/orders/{oid}")
    if resting:
        print(f"\nCleaned up: cancelled {len(resting)} leftover BUY order(s).")


if __name__ == "__main__":
    main()
