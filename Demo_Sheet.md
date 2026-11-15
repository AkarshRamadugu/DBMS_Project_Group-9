# DBMS Project — Demo Sheet
**Complete before the lab demo. Submit as a single-page PDF.**

---

## Header

| Field | Value |
|---|---|
| **Team ID / Lab section** | Group 9 |
| **Members** | Devansh Rupesh Anadkat (2024ADPS0198H), Akarsh Ramadugu (2024ADPS0196H), Shashank Bodala (2024ADPS0186H), Druhin Sourya Datta Bommisetti (2024ADPS0182H), Hakimkari Sathvika (2024ADPS0192H) |
| **GitHub repository** | https://github.com/AkarshRamadugu/DBMS_Project_Group-9 |
| **Final commit hash** | `035836193baae7623ad2515fe9a1ffe22a58b192` (tag: `final`) |
| **RDBMS & stack** | PostgreSQL 16 · FastAPI (Python, psycopg3) · Streamlit · Docker Compose |
| **Number of tables** | 12 |
| **Total database records** | ≈ 1,380 on a fresh setup (168 seed rows + 1,260 synthetic price bars from `seed_prices.py`); grows with every order, trade and audit entry |

---

## A. Application Workflows (≥ 3)

| # | Workflow / Purpose | DBMS Aspect | Tables Involved | UI Action → Database Effect |
|---|---|---|---|---|
| 1 | **Limit-Order Matching & Settlement** — Place a BUY or SELL limit order; engine matches against resting counter-orders and settles all fills atomically | SERIALIZABLE transaction · `SELECT … FOR UPDATE` row-locking · `match_and_settle` stored procedure · `fn_fill_qty_sync` trigger | `trade_order`, `trade`, `order_fill`, `position`, `cash_ledger`, `account` | User clicks "Submit Order" → `INSERT trade_order` → `CALL match_and_settle()` → `TRADE` rows created, `ORDER_FILL` rows inserted, `POSITION` upserted, `ACCOUNT.cash_balance` debited/credited, `AUDIT_LOG` written, order status updated to FILLED/PARTIAL |
| 2 | **Portfolio Dashboard** — View real-time unrealized P&L and portfolio value for any account | Multi-CTE · `DISTINCT ON` latest price · Window `SUM() OVER ()` · `portfolio_view` and `portfolio_summary_view` | `position`, `account`, `instrument`, `price_bar` | User selects account → `portfolio_view` queried via `GET /analytics/portfolio/{id}` → live market value and unrealized P&L computed from latest `price_bar.close` |
| 3 | **Integrity & Constraint Demo** — Attempt to place an order on an EXPIRED instrument or with insufficient cash | CHECK constraints · `fn_expired_instrument` BEFORE trigger · application-level pre-check | `instrument`, `account`, `trade_order` | User submits order → trigger fires `RAISE EXCEPTION 'integrity_constraint_violation'` → FastAPI maps to HTTP 400 → Streamlit shows error message |

---

## B. Non-Trivial SQL Queries (≥ 5)

| # | Query Purpose | SQL Concepts | Source File : Line | Workflow / Screen |
|---|---|---|---|---|
| 1 | **Order Book Depth with Running Total** — Aggregates open orders by price level, computes cumulative depth with a running window sum | `GROUP BY`, `SUM() OVER (PARTITION BY side ORDER BY CASE WHEN…)`, CTE | `db/queries/001_analytical_queries.sql` : 20–49  `backend/app/routers/analytics.py` : 28–64 | Market Overview → Order Book Depth table |
| 2 | **Portfolio Valuation & Unrealized P&L** — Joins positions with latest OHLCV close per instrument via `DISTINCT ON`, computes market value and P&L | Multi-CTE, `DISTINCT ON`, multi-table `JOIN`, `SUM() OVER ()` window | `db/queries/001_analytical_queries.sql` : 57–92  `backend/app/routers/analytics.py` : 89–128 | Portfolio page → Positions table |
| 3 | **Realized P&L per Account** — Separates buy costs from sell proceeds per instrument using conditional aggregation | 4-table `JOIN`, `CASE` conditional aggregation, `COUNT(DISTINCT …)` | `db/queries/001_analytical_queries.sql` : 100–118  `backend/app/routers/analytics.py` : 158–181 | Portfolio page → Realized P&L table |
| 4 | **Rolling 30-Day Return & Max Drawdown** — Computes daily rolling return vs 30 trading days prior and worst peak-to-trough decline in a 30-day window | `LAG(close,30)`, `MAX() OVER (UNBOUNDED PRECEDING)` running peak, `MIN() OVER (ROWS BETWEEN 29 PRECEDING…)` drawdown | `db/queries/001_analytical_queries.sql` : 126–172  `backend/app/routers/analytics.py` : 206–258 | Analytics page → Rolling 30-Day Returns chart |
| 5 | **Volume-Weighted Average Price (VWAP) per Day** — Computes VWAP from matched trade price × quantity, guarded by `NULLIF` for empty days | `SUM(p×q)/NULLIF(SUM(q),0)`, `GROUP BY DATE(executed_at)`, multi-table `JOIN` | `db/queries/001_analytical_queries.sql` : 180–194  `backend/app/routers/analytics.py` : 283–304 | Market Overview → VWAP table |
| 6 | **Accounts Where Holdings Exceed Cash Balance** — Lateral correlated subquery computes latest market value of all positions per account, filters those exceeding cash | `JOIN LATERAL`, correlated scalar subquery for latest price, `COALESCE` | `db/queries/001_analytical_queries.sql` : 201–233  `backend/app/routers/analytics.py` : 321–358 | Analytics page → Holdings vs Cash table |
| 7 | **Bond Yield-to-Maturity (YTM) Approximation** — Joins instrument supertype with bond subtype, fetches latest price via `LATERAL`, applies YTM formula | Subtype `JOIN` (`instrument ⋈ bond`), `JOIN LATERAL` for latest price, financial date arithmetic | `db/queries/001_analytical_queries.sql` : 242–271  `backend/app/routers/analytics.py` : 366–472 | Analytics page → Bond YTM Calculator |

---

## C. Additional DBMS Features (≥ 3)

| # | Feature | Object / Function Name | Source File : Line | Purpose / Effect |
|---|---|---|---|---|
| 1 | **SERIALIZABLE Transaction** | `match_and_settle(p_order_id)` | `db/procedures/001_match_and_settle.sql` : 15–339  `backend/app/routers/orders.py` : 136 | Prevents phantom reads during order matching; `SELECT … FOR UPDATE SKIP LOCKED` row-locks resting orders; retries on `SerializationFailure` / deadlock; the API feeds the matcher one order at a time so concurrent orders never deadlock |
| 2 | **Stored Procedures** | `match_and_settle(BIGINT)` · `end_of_day(DATE)` | `db/procedures/001_match_and_settle.sql` : 15  `db/procedures/002_end_of_day.sql` : 13 | (1) Full order-matching engine — creates TRADE, ORDER_FILL, updates POSITION and ACCOUNT.cash_balance; (2) Nightly batch — pays bond coupons, settles expiring options, marks instruments EXPIRED |
| 3 | **Triggers (5)** | `trg_audit_*` · `trg_subtype_bond/option` · `trg_trade_validation` · `trg_expired_instrument` · `trg_fill_qty_sync` | `db/triggers/001_triggers.sql` : 72–360 | Audit log (AFTER DML on 7 tables); ISA disjointness enforcement (BEFORE INSERT on bond/option); trade cross-validation (buy+sell same instrument, correct sides); expired-instrument rejection; filled_qty sync and status update |
| 4 | **Views (3)** | `order_book_view` · `portfolio_view` · `portfolio_summary_view` | `db/views/001_views.sql` : 30, 87, 139 | Reusable aggregated projections: order book depth (grouped by instrument/side/price), per-position market value and P&L (LATERAL latest price), account-level portfolio summary with COALESCE for cash-only accounts |
| 5 | **Indexes (11)** | `idx_trade_order_book` (partial) · `idx_price_bar_latest` (DESC) · 9 FK-support indexes | `db/migrations/001_schema.sql` : 336–358 | Partial index on OPEN/PARTIAL orders only (keeps index small); DESC composite index for "latest close per instrument" lookups; FK indexes eliminate seq scans on join columns |

