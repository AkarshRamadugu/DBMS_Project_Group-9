# Paper-Trading Exchange

A full-stack paper trading platform simulating a financial exchange with **limit-order matching**, **multi-instrument support** (stocks, bonds, options), **settlement**, **portfolio management**, and a complete **audit trail**.

Built for BITS Pilani CS F212 Database Systems — the design prioritises relational database depth over framework magic: hand-normalised BCNF schema, raw SQL everywhere, PL/pgSQL stored procedures, and SERIALIZABLE transactions.

---

## Quick Start

```bash
docker compose up -d --build
```

| Service | URL |
|---|---|
| Streamlit dashboard | http://localhost:8501 |
| FastAPI (REST + docs) | http://localhost:8000/docs |
| PostgreSQL | localhost:5432 (`db: paper_trading`, `user: trader`, `password: changeme`) |

The database is initialized and seeded automatically on first run (3 users, 10 instruments, 10 days of OHLCV per instrument, initial positions). After running `seed_prices.py` the total row count exceeds 1,300 (well above the 500-record requirement).

To seed 252 trading days of price bars (for >500 rows and 30-day rolling returns) and run the 7 standalone SQL queries:

```powershell
# PowerShell — seed 252 days of OHLCV bars via the backend container
Get-Content scripts/seed_prices.py | docker compose exec -T backend python -

# PowerShell — run the 7 analytical queries directly in PostgreSQL
Get-Content db/queries/001_analytical_queries.sql | docker compose exec -T postgres psql -U trader -d paper_trading
```

```bash
# Bash / Git Bash equivalent
cat scripts/seed_prices.py | docker compose exec -T backend python -
cat db/queries/001_analytical_queries.sql | docker compose exec -T postgres psql -U trader -d paper_trading
```

---

## Architecture

```
Browser (Streamlit)
      │  REST/JSON
FastAPI (Python · psycopg3 · no ORM)
      │  Raw SQL
PostgreSQL 16
  ├─ 12 relations (BCNF)
  ├─ 2 stored procedures  (match_and_settle, end_of_day)
  ├─ 5 triggers           (audit, subtype, trade-validation, expiry, fill-sync)
  ├─ 3 views              (order_book, portfolio, portfolio_summary)
  └─ 2 query indexes      (1 partial: open orders; 1 DESC: latest price bars)
```

### Technology Stack

| Layer | Technology |
|---|---|
| Database | PostgreSQL 16 (PL/pgSQL procedures, triggers, views, partial index) |
| Backend | Python 3.12 · FastAPI · psycopg 3 (async pool) — hand-written SQL, no ORM |
| Frontend | Streamlit 1.39 · Plotly · pandas |
| Packaging | Docker Compose (postgres, backend, frontend) |

### Frontend Pages

| Page | What it shows / does |
|---|---|
| **Market Overview** | Quote header, candlestick + volume chart (SMA 20/50), live **Order Book Depth** ladder with cumulative quantity, depth chart, **VWAP** table, Market Watch for all instruments |
| **Place Order** | Order ticket (BUY/SELL, limit price, qty) with pre-trade checks (cash × multiplier, holdings), live depth, confirmation with fills |
| **Portfolio** | Net worth / cash / unrealized P&L cards, **Positions** table, allocation charts, **Realized P&L** tab, **Cash Ledger** tab, deposit funds |
| **Order History** | Order blotter with status filters; select OPEN/PARTIAL orders and cancel them |
| **Analytics** | Rolling 30-day return, max drawdown, 30-day price channel, **Holdings vs Cash** report, **Bond YTM** calculator |

The trading account is chosen in the sidebar (the house / market-maker account is included so SELL liquidity can be demonstrated).

---

## Application Workflows

1. **Place, match and settle an order (transaction).** Place Order → `POST /orders` inserts a `trade_order` row and calls `match_and_settle()` in one SERIALIZABLE transaction. Matching uses price-time priority with `SELECT … FOR UPDATE`; each fill creates `trade` + two `order_fill` rows, upserts both `position` rows, writes two `cash_ledger` entries, updates both `account.cash_balance`, and the triggers sync `filled_qty`/status and write `audit_log`.
2. **Portfolio and market reporting (complex retrieval).** Portfolio and Market Overview pages call the analytics endpoints (CTEs, `DISTINCT ON`, `LATERAL`, window functions) for positions with unrealized P&L, realized P&L, order-book depth with running totals, VWAP, rolling returns/drawdown and bond YTM.
3. **Integrity enforcement.** Invalid actions are rejected by the database: overspend (`account.cash_balance >= 0` CHECK + API pre-check), oversell (procedure check + `position.qty >= 0`), orders on EXPIRED instruments (`trg_expired_instrument`), wrong subtype rows (`trg_subtype_bond/option`), duplicate coupon payouts (`uq_cash_ledger_idempotent`). The UI shows the database's error message.

### Concurrency

Many clients can submit orders simultaneously. Each order runs in its own SERIALIZABLE transaction with row locks; the API hands incoming orders to the matching engine one at a time (like a real exchange's sequential matcher, which price-time priority requires), so two matches can never lock the same accounts in opposite order. Serialization failures and deadlocks caused by other writers (cancels, deposits) are retried automatically. `scripts/run_stress_test.py` (10–20 threads, hundreds of orders) verifies cash-ledger, fill-quantity and non-negative-position invariants afterwards.

Live demo of simultaneous orders (12 buyers hit one 50-unit SELL order at the same instant; exactly 50 units fill, the rest rest in the book, invariants are checked):

```powershell
Get-Content scripts/demo_concurrent_orders.py | docker compose exec -T backend python -
```

---

## Project Structure

```
project/
├── Midsem/                              # Mid-semester report, ER & schema diagrams
├── db/
│   ├── migrations/001_schema.sql        # 12-relation DDL, all constraints & indexes
│   ├── triggers/001_triggers.sql        # 5 trigger functions
│   ├── procedures/
│   │   ├── 001_match_and_settle.sql     # Order-matching engine
│   │   └── 002_end_of_day.sql          # Coupon payments & option settlement
│   ├── views/001_views.sql              # order_book, portfolio, portfolio_summary
│   ├── queries/001_analytical_queries.sql # Standalone 7 analytical SQL queries
│   ├── seed/001_seed.sql               # Users, instruments, price bars, positions
│   └── init.sh                         # Docker init: runs SQL files in order
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI app + lifespan + CORS
│   │   ├── config.py                   # pydantic-settings env config
│   │   ├── database.py                 # Async psycopg3 connection pool
│   │   └── routers/
│   │       ├── instruments.py          # List, detail, price-bars, order-book
│   │       ├── accounts.py             # Accounts, positions, ledger, deposit
│   │       ├── orders.py               # Place (SERIALIZABLE), cancel, fills
│   │       └── analytics.py            # 7 non-trivial SQL query endpoints
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── app.py                          # 5-page Streamlit trading terminal (pages & layout)
│   ├── api.py                          # REST client for the FastAPI backend + short-TTL caching
│   ├── ui.py                           # Theme, number formatting, depth ladder, tables
│   ├── .streamlit/config.toml          # Dark theme
│   ├── Dockerfile
│   └── requirements.txt
├── scripts/
│   ├── seed_prices.py                  # GBM synthetic OHLCV or NSE bhavcopy CSV
│   ├── demo_concurrent_orders.py       # Live demo: simultaneous orders on one SELL order
│   └── run_stress_test.py              # 10-thread concurrency + invariant checks
└── docker-compose.yml
```

---

## Database Schema

12 relations, 16 foreign keys. Every relation is in BCNF over its base attributes. A few **derived** values are stored on purpose (controlled denormalization), each kept consistent inside the same transaction:

| Stored value | Derivable from | FD it adds | How consistency is guaranteed |
|---|---|---|---|
| `account.cash_balance` | SUM of `cash_ledger.amount` | — (aggregate) | updated in the settlement transaction; `chk_account_cash_balance` |
| `trade_order.filled_qty`, `status` | SUM of `order_fill.qty` | — (aggregate) | recomputed by `trg_fill_qty_sync` |
| `position.qty`, `avg_cost` | the account's trades | — (aggregate) | upserted in the settlement transaction under `FOR UPDATE` |
| `order_fill.qty`, `price`, `filled_at` | the parent `trade` row | `trade_id → qty, price` | written with the trade in `match_and_settle`; `trg_fill_qty_sync` rejects a fill whose qty/price differ from its trade |

`scripts/run_stress_test.py` and `scripts/demo_concurrent_orders.py` check these invariants after concurrent load.

| Relation | PK | Notes |
|---|---|---|
| `user_account` | `user_id` | Email UNIQUE |
| `account` | `account_id` | Cash balance ≥ 0 |
| `instrument` | `instrument_id` | Symbol UNIQUE; type ∈ STOCK/BOND/OPTION |
| `bond` | `instrument_id` (FK) | ISA subtype; face value, coupon, maturity |
| `option` | `instrument_id` (FK) | ISA subtype; strike, expiry, CALL/PUT |
| `price_bar` | `(instrument_id, trade_date)` | Weak entity; HIGH ≥ LOW |
| `trade_order` | `order_id` | Partial index on OPEN/PARTIAL orders |
| `trade` | `trade_id` | Buy + sell order FKs |
| `order_fill` | `(order_id, fill_seq)` | Weak entity; fill_qty sync via trigger |
| `position` | `(account_id, instrument_id)` | M:N; qty ≥ 0 |
| `cash_ledger` | `ledger_id` | Double-entry; UNIQUE prevents double payouts |
| `audit_log` | `log_id` | No FK — survives row deletions |

---

## DBMS Features

| Feature | Implementation |
|---|---|
| **Transactions** | `match_and_settle` runs fully in `SERIALIZABLE` with `SELECT ... FOR UPDATE` row-locking |
| **Stored Procedures** | `match_and_settle(order_id)` — matching engine; `end_of_day(date)` — coupons & option expiry |
| **Triggers** | Audit log, ISA subtype disjointness, trade cross-validation, expired-instrument rejection, fill-qty sync |
| **Views** | `order_book_view`, `portfolio_view`, `portfolio_summary_view` |
| **Indexes** | Partial index on open orders; DESC index on price bars for latest-price queries |

---

## Analytics Endpoints

| Route | SQL Concepts |
|---|---|
| `GET /analytics/order-book-depth/{id}` | `SUM() OVER` running total |
| `GET /analytics/portfolio/{account_id}` | CTE + `DISTINCT ON` for latest price |
| `GET /analytics/realized-pnl/{account_id}` | Multi-join, `CASE`, aggregate |
| `GET /analytics/rolling-returns/{id}` | `LAG(close, 30)`, `MAX OVER` running peak, `MIN OVER … ROWS BETWEEN` |
| `GET /analytics/vwap/{id}` | Weighted avg `SUM(p×q)/SUM(q)`, GROUP BY day |
| `GET /analytics/holdings-vs-cash` | `LATERAL` correlated subquery |
| `GET /analytics/bond-ytm/{id}` | YTM approximation formula |

All seven queries are defined in `db/queries/001_analytical_queries.sql` and mirrored in `backend/app/routers/analytics.py`. Query 1 returns each side best-price-first so its cumulative depth column is monotonic top-to-bottom.

---

## Co-Developer & Container Workflow

### First-Time Setup on Your Machine
Make sure **Docker Desktop** is running, then clone and start the stack:

```bash
git clone https://github.com/AkarshRamadugu/DBMS_Project_Group-9.git
cd DBMS_Project_Group-9
docker compose up -d --build
```

> **Port 5432 conflict:** If you already have a local PostgreSQL service running on your machine, stop it first (otherwise the `postgres` container will fail to bind port `5432`).

### Editing Code Without Rebuilding
- `docker-compose.yml` mounts `./backend:/app` and `./frontend:/app`, so edits to FastAPI or Streamlit Python files hot-reload automatically without rebuilding images.
- `.gitattributes` locks `*.sh`, `*.sql`, `Dockerfile`, and `*.yml` to LF (`\n`) line endings so Windows teammates won't break `db/init.sh` inside the Linux Postgres container.

### When Dependencies or SQL Files Change
- **If `db/` (`*.sql`) changed:** PostgreSQL only runs `db/init.sh` when the `pgdata` volume is empty. After pulling SQL changes, wipe the volume and recreate the containers:
  ```bash
  docker compose down -v
  docker compose up -d --build
  ```
- **If `requirements.txt` or a `Dockerfile` changed:** rebuild the images:
  ```bash
  docker compose up -d --build
  ```

### Git Workflow (Avoiding Merge Conflicts)
Work on your own feature branch instead of pushing directly over someone else's edits on `main`:

```bash
git checkout main
git pull origin main
git checkout -b <your-name>/<feature>    # e.g. devansh/eod-tests
# ...edit, test, and commit...
git push -u origin <your-name>/<feature>
```

Then open a Pull Request into `main` on GitHub (or run `git pull --rebase origin main` before pushing). Never commit local `.env` files (`.gitignore` ignores them automatically).

---

## Running Without Docker

```powershell
# 1. Start PostgreSQL 16 locally, then:
psql -d paper_trading -f db/migrations/001_schema.sql
psql -d paper_trading -f db/triggers/001_triggers.sql
psql -d paper_trading -f db/procedures/001_match_and_settle.sql
psql -d paper_trading -f db/procedures/002_end_of_day.sql
psql -d paper_trading -f db/views/001_views.sql
psql -d paper_trading -f db/seed/001_seed.sql

# 2. Backend
Set-Location backend; Copy-Item .env.example .env   # edit credentials
pip install -r requirements.txt
uvicorn app.main:app --reload

# 3. Frontend (new terminal)
Set-Location frontend
pip install -r requirements.txt
streamlit run app.py

# 4. Seed 252 trading days of synthetic price data for stocks (needed for 30-day rolling returns & 500+ rows)
python scripts/seed_prices.py

# 5. (Optional) Run the 7 analytical SQL queries directly in psql
psql -d paper_trading -f db/queries/001_analytical_queries.sql

# 6. (Optional) Concurrency stress test
python scripts/run_stress_test.py
```

---

## Final Submission

| Item | Value |
|---|---|
| **Submission deadline** | Sunday, 15 November 2026, 11:59 PM |
| **Demo dates** | 17–19 November 2026 (respective lab sessions) |
| **Final commit hash** | `ca88de0607cd55abbae59d9c9c8524f554da7693` (tag: `final`) |
| **GitHub repo** | https://github.com/AkarshRamadugu/DBMS_Project_Group-9 |

### Tagging the final commit

After the last push before the deadline, tag and push the tag:

```powershell
git tag final
git push origin final
```

Then record `git rev-parse HEAD` in this table and in the Demo Sheet PDF.

---

## Changes from the Mid-Semester Plan

The schema (12 relations, keys, constraints), the 5 triggers, both stored procedures, the 7 queries and the 3 workflows were implemented as planned. Differences:

| Mid-sem plan | Final implementation |
|---|---|
| 2 views | 3 views (`portfolio_summary_view` added for account-level totals incl. cash-only accounts) |
| 2 indexes | The 2 planned query indexes, plus 9 indexes on foreign-key columns |
| Latest price via `ROW_NUMBER` | `DISTINCT ON` / `LATERAL … LIMIT 1` (same result, uses `idx_price_bar_latest`) |
| Bond YTM as a stored function | Parameterised SQL query (`db/queries`, `/analytics/bond-ytm`) |
| Price data from NSE bhavcopy; bonds from yield curves; options from Black-Scholes | `seed_prices.py` loads a bhavcopy CSV via `COPY` (`--csv`) or generates 252 days of synthetic GBM bars for the stocks. Bonds and options use the hand-written bars in `db/seed/001_seed.sql`; yield-curve and Black-Scholes pricing were not implemented |
| "Input validation & auth" in the API | Input validation via Pydantic and database constraints. No login/authentication: `user_account.password_hash` is stored but the demo selects accounts from the sidebar |
| Streamlit or React | Streamlit |

---

## Team

| Name | ID | Responsibilities |
|---|---|---|
| Devansh Rupesh Anadkat | 2024ADPS0198H | ER/EER model, 9-step schema mapping, `match_and_settle` design |
| Akarsh Ramadugu | 2024ADPS0196H | BCNF normalization proof, 7 analytical SQL queries, index strategy, database views |
| Shashank Bodala | 2024ADPS0186H | Integrity constraints, trigger specifications |
| Druhin Sourya Datta Bommisetti | 2024ADPS0182H | Application architecture, FastAPI backend, workflows |
| Hakimkari Sathvika | 2024ADPS0192H | Data pipeline, price seeding, repository organisation |
