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

The database is initialized and seeded automatically on first run (3 users, 10 instruments, 10 days of OHLCV, initial positions).

To seed 252 trading days of price bars (for >500 rows and 30-day rolling returns) and run the 7 standalone SQL queries:

```bash
# Seed 252 days of OHLCV bars via the backend container (works in PowerShell & Bash)
cat scripts/seed_prices.py | docker compose exec -T backend python -

# Run the 7 analytical queries directly in PostgreSQL
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
  └─ 2 partial indexes    (open orders, latest price bars)
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
│   ├── app.py                          # 5-page Streamlit dashboard
│   ├── Dockerfile
│   └── requirements.txt
├── scripts/
│   ├── seed_prices.py                  # GBM synthetic OHLCV or NSE bhavcopy CSV
│   └── run_stress_test.py              # 10-thread concurrency + invariant checks
└── docker-compose.yml
```

---

## Database Schema

12 relations, 16 foreign keys, all in BCNF.

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
| `GET /analytics/rolling-returns/{id}` | `LAG(close, 30)`, `MIN OVER … ROWS BETWEEN` |
| `GET /analytics/vwap/{id}` | Weighted avg `SUM(p×q)/SUM(q)`, GROUP BY day |
| `GET /analytics/holdings-vs-cash` | `LATERAL` correlated subquery |
| `GET /analytics/bond-ytm/{id}` | YTM approximation formula |

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

```bash
# 1. Start PostgreSQL 16 locally, then:
psql -d paper_trading -f db/migrations/001_schema.sql
psql -d paper_trading -f db/triggers/001_triggers.sql
psql -d paper_trading -f db/procedures/001_match_and_settle.sql
psql -d paper_trading -f db/procedures/002_end_of_day.sql
psql -d paper_trading -f db/views/001_views.sql
psql -d paper_trading -f db/seed/001_seed.sql

# 2. Backend
cd backend && cp .env.example .env   # edit credentials
pip install -r requirements.txt
uvicorn app.main:app --reload

# 3. Frontend (new terminal)
cd frontend
pip install -r requirements.txt
streamlit run app.py

# 4. Seed 252 trading days of synthetic price data (needed for 30-day rolling returns & 500+ rows)
python scripts/seed_prices.py

# 5. (Optional) Run the 7 analytical SQL queries directly in psql
psql -d paper_trading -f db/queries/001_analytical_queries.sql

# 6. (Optional) Concurrency stress test
python scripts/run_stress_test.py
```

---

## Team

| Name | ID | Responsibilities |
|---|---|---|
| Devansh Rupesh Anadkat | 2024ADPS0198H | ER/EER model, 9-step schema mapping, `match_and_settle` design |
| Akarsh Ramadugu | 2024ADPS0196H | BCNF normalization, analytical SQL queries, indexes, views |
| Shashank Bodala | 2024ADPS0186H | Integrity constraints, trigger specifications |
| Druhin Sourya Datta Bommisetti | 2024ADPS0182H | Application architecture, FastAPI backend, workflows |
| Hakimkari Sathvika | 2024ADPS0192H | Data pipeline, price seeding, repository organisation |
