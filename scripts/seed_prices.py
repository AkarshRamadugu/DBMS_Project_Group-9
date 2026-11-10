"""
scripts/seed_prices.py
======================
Seeds the `price_bar` table with historical OHLCV data.

Usage
-----
# Synthetic data (default):
    python scripts/seed_prices.py

# From a real NSE bhavcopy CSV:
    python scripts/seed_prices.py --csv path/to/bhavcopy.csv

Environment variables (all optional, fall back to defaults):
    POSTGRES_HOST     default: localhost
    POSTGRES_PORT     default: 5432
    POSTGRES_DB       default: paper_trading
    POSTGRES_USER     default: trader
    POSTGRES_PASSWORD default: changeme
"""

import argparse
import csv
import io
import math
import os
import random
import sys
from datetime import date, timedelta

import psycopg

# ---------------------------------------------------------------------------
# Database connection helper
# ---------------------------------------------------------------------------
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
# GBM synthetic data parameters
# ---------------------------------------------------------------------------
SYNTHETIC_PARAMS = {
    "RELIANCE":  {"start_price": 2800.0},
    "TCS":       {"start_price": 3900.0},
    "INFY":      {"start_price": 1700.0},
    "HDFCBANK":  {"start_price": 1600.0},
    "WIPRO":     {"start_price":  500.0},
}
DRIFT = 0.0003   # daily drift μ
SIGMA = 0.015    # daily volatility σ
TRADING_DAYS = 252


def _trading_dates(n: int) -> list[date]:
    """Return the last n weekdays ending today."""
    dates: list[date] = []
    day = date.today()
    while len(dates) < n:
        if day.weekday() < 5:          # Mon–Fri
            dates.append(day)
        day -= timedelta(days=1)
    dates.reverse()
    return dates


def generate_synthetic_ohlcv(symbol: str, start_price: float, n: int = TRADING_DAYS):
    """
    Simulate daily OHLCV using Geometric Brownian Motion.

    Returns a list of dicts with keys:
        trade_date, open, high, low, close, volume
    """
    rng = random.Random(hash(symbol))   # reproducible per symbol
    dates = _trading_dates(n)
    rows = []
    price = start_price

    for trade_date in dates:
        # GBM step
        z = rng.gauss(0.0, 1.0)
        daily_return = math.exp((DRIFT - 0.5 * SIGMA ** 2) + SIGMA * z)
        close = round(price * daily_return, 2)

        # Intraday range: ±(σ/2) around the open/close range
        intra_range = price * SIGMA * rng.uniform(0.5, 1.5)
        open_price = round(price * math.exp(rng.gauss(0.0, SIGMA * 0.5)), 2)
        high = round(max(open_price, close) + intra_range * rng.uniform(0.0, 1.0), 2)
        low  = round(min(open_price, close) - intra_range * rng.uniform(0.0, 1.0), 2)
        low  = max(low, 0.01)                   # never negative

        volume = rng.randint(100_000, 5_000_000)

        rows.append({
            "trade_date": trade_date,
            "open":        open_price,
            "high":        high,
            "low":         low,
            "close":       close,
            "volume":      volume,
        })

        price = close   # next day opens near previous close

    return rows


def _symbol_to_instrument_id(conn) -> dict[str, int]:
    """Fetch symbol → instrument_id mapping from the DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, instrument_id FROM instrument;")
        return {row[0]: row[1] for row in cur.fetchall()}


def bulk_insert(conn, rows: list[tuple]):
    """
    Bulk-insert into price_bar using COPY.

    Each tuple: (instrument_id, trade_date, open, high, low, close, volume)
    """
    buf = io.StringIO()
    for r in rows:
        buf.write("\t".join(str(v) for v in r) + "\n")
    buf.seek(0)

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE tmp_price_bar
                (LIKE price_bar INCLUDING DEFAULTS)
            ON COMMIT DROP;
            """
        )
        with cur.copy(
            "COPY tmp_price_bar (instrument_id, trade_date, open, high, low, close, volume) FROM STDIN"
        ) as copy:
            copy.write(buf.read())

        cur.execute(
            """
            INSERT INTO price_bar
                        (instrument_id, trade_date, open, high, low, close, volume)
            SELECT instrument_id, trade_date, open, high, low, close, volume
            FROM   tmp_price_bar
            ON CONFLICT (instrument_id, trade_date) DO UPDATE
                SET open   = EXCLUDED.open,
                    high   = EXCLUDED.high,
                    low    = EXCLUDED.low,
                    close  = EXCLUDED.close,
                    volume = EXCLUDED.volume;
            """
        )
    conn.commit()


# ---------------------------------------------------------------------------
# NSE bhavcopy ingestion
# ---------------------------------------------------------------------------
NSE_COLUMNS = {
    "SYMBOL":     "symbol",
    "OPEN":       "open",
    "HIGH":       "high",
    "LOW":        "low",
    "CLOSE":      "close",
    "TOTTRDQTY":  "volume",
    "TIMESTAMP":  "trade_date",
    "SERIES":     "series",
}


def load_bhavcopy(csv_path: str, conn):
    """Read NSE bhavcopy CSV and insert into price_bar."""
    sym_map = _symbol_to_instrument_id(conn)
    rows: list[tuple] = []

    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for line in reader:
            # Accept EQ series only (equity stocks)
            if line.get("SERIES", "EQ").strip() not in ("EQ", ""):
                continue

            symbol = line.get("SYMBOL", "").strip()
            instrument_id = sym_map.get(symbol)
            if instrument_id is None:
                continue    # not in our DB — skip

            try:
                trade_date = line["TIMESTAMP"].strip()   # e.g. "10-NOV-2024"
                # Convert "DD-MON-YYYY" → ISO date if needed
                try:
                    from datetime import datetime
                    trade_date = datetime.strptime(trade_date, "%d-%b-%Y").date()
                except ValueError:
                    pass   # already ISO

                rows.append((
                    instrument_id,
                    trade_date,
                    float(line["OPEN"]),
                    float(line["HIGH"]),
                    float(line["LOW"]),
                    float(line["CLOSE"]),
                    int(float(line["TOTTRDQTY"])),
                ))
            except (KeyError, ValueError) as exc:
                print(f"  [skip] {symbol}: {exc}", file=sys.stderr)

    if rows:
        bulk_insert(conn, rows)
        print(f"Inserted {len(rows)} rows from bhavcopy.")
    else:
        print("No matching rows found in bhavcopy CSV.")


# ---------------------------------------------------------------------------
# Synthetic data runner
# ---------------------------------------------------------------------------
def run_synthetic(conn):
    sym_map = _symbol_to_instrument_id(conn)
    total = 0

    for symbol, params in SYNTHETIC_PARAMS.items():
        instrument_id = sym_map.get(symbol)
        if instrument_id is None:
            print(f"  [skip] {symbol} not found in instrument table.")
            continue

        ohlcv = generate_synthetic_ohlcv(symbol, params["start_price"])
        rows = [
            (
                instrument_id,
                r["trade_date"],
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
            )
            for r in ohlcv
        ]
        bulk_insert(conn, rows)
        total += len(rows)
        print(f"  {symbol}: inserted {len(rows)} synthetic price bars.")

    print(f"Done — {total} rows total.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Seed price_bar table.")
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="Path to NSE bhavcopy CSV. If omitted, synthetic data is generated.",
        default=None,
    )
    args = parser.parse_args()

    print(f"Connecting to database …  ({DSN.split('password')[0].strip()})")
    with psycopg.connect(DSN, autocommit=False) as conn:
        if args.csv:
            print(f"Loading bhavcopy from {args.csv} …")
            load_bhavcopy(args.csv, conn)
        else:
            print("Generating synthetic OHLCV data (GBM) …")
            run_synthetic(conn)


if __name__ == "__main__":
    main()
