"""
Paper-Trading Exchange — Streamlit Frontend
Multi-page application with sidebar navigation.
"""

import os
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL = os.environ.get("API_URL", "http://localhost:8000")


def api_get(path: str, params: dict = None):
    """GET from the backend API; returns parsed JSON or None on error."""
    try:
        resp = requests.get(f"{API_URL}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        st.error(f"API error [{path}]: {detail}")
        return None
    except requests.exceptions.RequestException as exc:
        st.error(f"API error [{path}]: {exc}")
        return None


def api_post(path: str, payload: dict):
    """POST to the backend API; returns parsed JSON or None on error."""
    try:
        resp = requests.post(f"{API_URL}{path}", json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        st.error(f"API error [{path}]: {detail}")
        return None
    except requests.exceptions.RequestException as exc:
        st.error(f"API error [{path}]: {exc}")
        return None


def api_delete(path: str):
    """DELETE via the backend API; returns parsed JSON or None on error."""
    try:
        resp = requests.delete(f"{API_URL}{path}", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        st.error(f"API error [{path}]: {detail}")
        return None
    except requests.exceptions.RequestException as exc:
        st.error(f"API error [{path}]: {exc}")
        return None


# ---------------------------------------------------------------------------
# Cached data-fetching helpers (ttl=5 s so live trading updates propagate)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=5)
def fetch_instruments():
    return api_get("/instruments") or []


@st.cache_data(ttl=5)
def fetch_accounts():
    """Fetch non-house accounts only."""
    return api_get("/accounts") or []


@st.cache_data(ttl=5)
def fetch_all_accounts():
    """Fetch ALL accounts including house (for Place Order SELL demo)."""
    # /accounts returns non-house; we complement with direct per-account calls
    # Simpler: fetch non-house accounts and also try to get house by id=1
    accounts = api_get("/accounts") or []
    house = api_get("/accounts/1")
    if house and house.get("is_house"):
        accounts = [house] + accounts
    return accounts


@st.cache_data(ttl=5)
def fetch_price_bars(instrument_id: int):
    return api_get(f"/instruments/{instrument_id}/price-bars", params={"days": 252}) or []


@st.cache_data(ttl=5)
def fetch_order_book_depth(instrument_id: int):
    return api_get(f"/analytics/order-book-depth/{instrument_id}") or []


@st.cache_data(ttl=5)
def fetch_vwap(instrument_id: int):
    return api_get(f"/analytics/vwap/{instrument_id}")


@st.cache_data(ttl=5)
def fetch_portfolio(account_id: int):
    return api_get(f"/analytics/portfolio/{account_id}") or {}


@st.cache_data(ttl=5)
def fetch_realized_pnl(account_id: int):
    return api_get(f"/analytics/realized-pnl/{account_id}") or []


@st.cache_data(ttl=5)
def fetch_orders(account_id: int, status: str):
    params = {"account_id": account_id}
    if status != "ALL":
        params["status"] = status
    return api_get("/orders", params=params) or []


@st.cache_data(ttl=5)
def fetch_rolling_returns(instrument_id: int):
    return api_get(f"/analytics/rolling-returns/{instrument_id}") or []


@st.cache_data(ttl=5)
def fetch_holdings_vs_cash():
    return api_get("/analytics/holdings-vs-cash") or []


@st.cache_data(ttl=5)
def fetch_bond_ytm(instrument_id: int):
    return api_get(f"/analytics/bond-ytm/{instrument_id}")


@st.cache_data(ttl=5)
def fetch_ledger(account_id: int, limit: int = 50):
    return api_get(f"/accounts/{account_id}/ledger", params={"limit": limit}) or []


def clear_all_caches():
    """Clear all cached data after a mutating operation."""
    fetch_instruments.clear()
    fetch_accounts.clear()
    fetch_all_accounts.clear()
    fetch_order_book_depth.clear()
    fetch_vwap.clear()
    fetch_portfolio.clear()
    fetch_realized_pnl.clear()
    fetch_orders.clear()
    fetch_rolling_returns.clear()
    fetch_holdings_vs_cash.clear()
    fetch_ledger.clear()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def instrument_options(instruments):
    """Return (label→id) mapping from instrument list."""
    return {f"{i['symbol']} — {i['name']}": i["instrument_id"] for i in instruments}


def account_options(accounts):
    """Return (label→id) mapping from account list."""
    return {
        f"{'🏦 ' if a.get('is_house') else ''}{a.get('user_name', 'Account')} "
        f"(#{a['account_id']} — Cash: ₹{float(a.get('cash_balance', 0)):,.2f})": a["account_id"]
        for a in accounts
    }


def style_pnl(val):
    """Colour positive P&L green, negative red."""
    try:
        colour = "green" if float(val) >= 0 else "red"
        return f"color: {colour}"
    except (ValueError, TypeError):
        return ""


# ===========================================================================
# Page 1 — Market Overview
# ===========================================================================
def page_market_overview():
    st.header("📊 Market Overview")

    instruments = fetch_instruments()
    if not instruments:
        st.warning("No instruments available.")
        return

    inst_map = instrument_options(instruments)
    selected_label = st.selectbox("Select Instrument", list(inst_map.keys()), key="mo_inst")
    instrument_id = inst_map[selected_label]

    # --- Candlestick chart ---
    st.subheader("OHLCV Price Chart (Last 252 Trading Days)")
    bars = fetch_price_bars(instrument_id)
    if bars:
        df = pd.DataFrame(bars)
        df.columns = [c.lower() for c in df.columns]
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

        fig = go.Figure()
        fig.add_trace(
            go.Candlestick(
                x=df.get("trade_date", df.index),
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name="OHLC",
            )
        )
        if "volume" in df.columns:
            fig.add_trace(
                go.Bar(
                    x=df.get("trade_date", df.index),
                    y=df["volume"],
                    name="Volume",
                    yaxis="y2",
                    marker_color="rgba(100,149,237,0.4)",
                )
            )
        fig.update_layout(
            title=f"Price History — {selected_label}",
            xaxis_title="Date",
            yaxis_title="Price (₹)",
            yaxis2=dict(title="Volume", overlaying="y", side="right", showgrid=False),
            xaxis_rangeslider_visible=False,
            height=500,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Latest price metrics
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        col1, col2, col3, col4 = st.columns(4)
        close_val = float(latest.get("close", 0))
        prev_close = float(prev.get("close", 0))
        delta = close_val - prev_close
        col1.metric("Latest Close", f"₹{close_val:,.2f}", f"{delta:+.2f}")
        col2.metric("Open", f"₹{float(latest.get('open', 0)):,.2f}")
        col3.metric("High", f"₹{float(latest.get('high', 0)):,.2f}")
        col4.metric("Low", f"₹{float(latest.get('low', 0)):,.2f}")
    else:
        st.info("No price bar data available for this instrument.")

    # --- Order book depth ---
    st.subheader("Order Book Depth")
    depth = fetch_order_book_depth(instrument_id)
    if depth:
        df_depth = pd.DataFrame(depth)
        # Split into BUY and SELL sides for cleaner display
        buys = df_depth[df_depth["side"] == "BUY"].sort_values("price", ascending=False) if "side" in df_depth.columns else pd.DataFrame()
        sells = df_depth[df_depth["side"] == "SELL"].sort_values("price", ascending=True) if "side" in df_depth.columns else pd.DataFrame()
        col_b, col_s = st.columns(2)
        with col_b:
            st.markdown("**🟢 BUY (Bids)**")
            if not buys.empty:
                st.dataframe(
                    buys[["price", "total_qty", "order_count", "cumulative_qty"] if "cumulative_qty" in buys.columns else ["price", "total_qty", "order_count"]].reset_index(drop=True),
                    use_container_width=True,
                )
            else:
                st.info("No bids.")
        with col_s:
            st.markdown("**🔴 SELL (Asks)**")
            if not sells.empty:
                st.dataframe(
                    sells[["price", "total_qty", "order_count", "cumulative_qty"] if "cumulative_qty" in sells.columns else ["price", "total_qty", "order_count"]].reset_index(drop=True),
                    use_container_width=True,
                )
            else:
                st.info("No asks.")
    else:
        st.info("No open orders in the order book for this instrument.")

    # --- VWAP ---
    st.subheader("VWAP (Volume-Weighted Average Price)")
    vwap_data = fetch_vwap(instrument_id)
    if vwap_data is not None and isinstance(vwap_data, list) and len(vwap_data) > 0:
        df_vwap = pd.DataFrame(vwap_data)
        df_vwap.columns = [c.replace("_", " ").title() for c in df_vwap.columns]
        st.dataframe(df_vwap, use_container_width=True)
    else:
        st.info("No VWAP data yet — place some orders to generate trades.")


# ===========================================================================
# Page 2 — Place Order
# ===========================================================================
def page_place_order():
    st.header("🛒 Place Order")

    # Include house account so we can demo SELL from house inventory
    all_accounts = fetch_all_accounts()
    instruments = fetch_instruments()

    if not all_accounts:
        st.warning("No accounts available.")
        return
    if not instruments:
        st.warning("No instruments available.")
        return

    # Only show ACTIVE instruments
    active_instruments = [i for i in instruments if str(i.get("status", "ACTIVE")).upper() == "ACTIVE"]
    if not active_instruments:
        st.warning("No active instruments available.")
        return

    acc_map = account_options(all_accounts)
    inst_map = instrument_options(active_instruments)

    col1, col2 = st.columns(2)
    with col1:
        selected_acc_label = st.selectbox("Account", list(acc_map.keys()), key="po_acc")
        account_id = acc_map[selected_acc_label]
    with col2:
        selected_inst_label = st.selectbox("Instrument", list(inst_map.keys()), key="po_inst")
        instrument_id = inst_map[selected_inst_label]

    side = st.radio("Order Side", ["BUY", "SELL"], horizontal=True, key="po_side")

    col3, col4 = st.columns(2)
    with col3:
        price = st.number_input(
            "Limit Price (₹)",
            min_value=0.01,
            value=100.00,
            step=0.05,
            format="%.2f",
            key="po_price",
        )
    with col4:
        qty = st.number_input(
            "Quantity",
            min_value=1,
            value=1,
            step=1,
            key="po_qty",
        )

    # Find selected account for balance display
    selected_acc = next((a for a in all_accounts if a["account_id"] == account_id), None)
    if selected_acc:
        cash = float(selected_acc.get("cash_balance", 0))
        order_cost = price * qty
        col_a, col_b = st.columns(2)
        col_a.metric("💰 Account Cash Balance", f"₹{cash:,.2f}")
        col_b.metric("📋 Order Value", f"₹{order_cost:,.2f}", delta=f"{'Sufficient ✓' if cash >= order_cost or side == 'SELL' else 'Insufficient ✗'}")

    if st.button("🚀 Submit Order", type="primary"):
        payload = {
            "account_id": account_id,
            "instrument_id": instrument_id,
            "side": side,
            "price": price,
            "qty": qty,
        }
        result = api_post("/orders", payload)
        if result is not None:
            status = result.get("status", "—")
            filled_qty = result.get("filled_qty", 0)
            order_id = result.get("order_id", "—")
            if status == "FILLED":
                st.success(f"✅ Order #{order_id} FILLED completely ({filled_qty}/{qty} qty)!")
            elif status == "PARTIAL":
                st.warning(f"⚡ Order #{order_id} PARTIALLY filled ({filled_qty}/{qty} qty). Remaining rests in book.")
            else:
                st.info(f"📋 Order #{order_id} placed — status: {status}")

            st.markdown(
                f"""
                | Field | Value |
                |---|---|
                | **Order ID** | {order_id} |
                | **Status** | {status} |
                | **Filled Qty** | {filled_qty} / {qty} |
                | **Side** | {side} |
                | **Fill Price** | ₹{price:,.2f} |
                """
            )
            fills = result.get("fills", [])
            if fills:
                st.subheader("Trade Fills")
                df_fills = pd.DataFrame(fills)
                for col in ["qty", "price"]:
                    if col in df_fills.columns:
                        df_fills[col] = pd.to_numeric(df_fills[col], errors="coerce")
                st.dataframe(df_fills, use_container_width=True)

            # Clear all caches so every page shows fresh data
            clear_all_caches()


# ===========================================================================
# Page 3 — Portfolio
# ===========================================================================
def page_portfolio():
    st.header("💼 Portfolio")

    accounts = fetch_accounts()
    if not accounts:
        st.warning("No accounts available.")
        return

    acc_map = account_options(accounts)
    selected_acc_label = st.selectbox("Account", list(acc_map.keys()), key="pf_acc")
    account_id = acc_map[selected_acc_label]

    # Cash balance + deposit
    selected_acc = next((a for a in accounts if a["account_id"] == account_id), None)
    if selected_acc:
        cash = float(selected_acc.get("cash_balance", 0))
        col_cash, col_dep = st.columns([2, 1])
        col_cash.metric("💰 Cash Balance", f"₹{cash:,.2f}")
        with col_dep:
            with st.expander("➕ Deposit Cash"):
                dep_amount = st.number_input(
                    "Deposit Amount (₹)",
                    min_value=1.0,
                    value=100000.0,
                    step=10000.0,
                    format="%.2f",
                    key="dep_amount",
                )
                if st.button("💸 Deposit", key="dep_btn"):
                    result = api_post(f"/accounts/{account_id}/deposit", {"amount": dep_amount})
                    if result is not None:
                        new_bal = float(result.get("new_cash_balance", 0))
                        st.success(f"✅ Deposited ₹{dep_amount:,.2f}. New balance: ₹{new_bal:,.2f}")
                        clear_all_caches()
                        st.rerun()

    # Tabs: Positions | Realized P&L | Cash Ledger
    tab1, tab2, tab3 = st.tabs(["📊 Positions", "💹 Realized P&L", "📒 Cash Ledger"])

    with tab1:
        portfolio_data = fetch_portfolio(account_id)
        positions = []
        if isinstance(portfolio_data, dict):
            positions = portfolio_data.get("positions", [])
        elif isinstance(portfolio_data, list):
            positions = portfolio_data

        if positions:
            df_pos = pd.DataFrame(positions)
            df_pos.columns = [c.lower() for c in df_pos.columns]
            for num_col in ["qty", "avg_cost", "latest_close", "current_price", "market_value", "unrealized_pnl"]:
                if num_col in df_pos.columns:
                    df_pos[num_col] = pd.to_numeric(df_pos[num_col], errors="coerce")

            # Summary metrics
            if isinstance(portfolio_data, dict):
                total_val = float(portfolio_data.get("positions", [{}])[0].get("total_holdings_value", 0) if portfolio_data.get("positions") else 0)
                cash_bal = float(portfolio_data.get("cash_balance", 0))
            else:
                total_val = df_pos["market_value"].sum() if "market_value" in df_pos.columns else 0
                cash_bal = float(selected_acc.get("cash_balance", 0)) if selected_acc else 0

            m1, m2, m3 = st.columns(3)
            m1.metric("Holdings Value", f"₹{total_val:,.2f}")
            m2.metric("Cash Balance", f"₹{cash_bal:,.2f}")
            m3.metric("Total Portfolio", f"₹{total_val + cash_bal:,.2f}")

            col_rename = {
                "symbol": "Symbol",
                "instrument_type": "Type",
                "qty": "Qty",
                "avg_cost": "Avg Cost (₹)",
                "latest_close": "Current Price (₹)",
                "current_price": "Current Price (₹)",
                "market_value": "Market Value (₹)",
                "unrealized_pnl": "Unrealized P&L (₹)",
            }
            display_cols = [c for c in col_rename if c in df_pos.columns]
            df_display = df_pos[display_cols].rename(columns=col_rename)

            pnl_col = "Unrealized P&L (₹)"
            if pnl_col in df_display.columns:
                try:
                    # Use map (pandas ≥2.1) with applymap fallback
                    styled = df_display.style.map(style_pnl, subset=[pnl_col])
                except AttributeError:
                    styled = df_display.style.applymap(style_pnl, subset=[pnl_col])
                st.dataframe(styled, use_container_width=True)
            else:
                st.dataframe(df_display, use_container_width=True)

            # Pie chart
            if "instrument_type" in df_pos.columns and "market_value" in df_pos.columns:
                alloc = df_pos.groupby("instrument_type")["market_value"].sum().reset_index()
                alloc.columns = ["Type", "Market Value (₹)"]
                fig_pie = px.pie(alloc, names="Type", values="Market Value (₹)", title="Portfolio Allocation", hole=0.35)
                st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No positions held in this account.")

    with tab2:
        realized = fetch_realized_pnl(account_id)
        if realized:
            df_rpnl = pd.DataFrame(realized)
            df_rpnl.columns = [c.lower() for c in df_rpnl.columns]
            for col in ["total_buy_cost", "total_sell_proceeds", "realized_pnl"]:
                if col in df_rpnl.columns:
                    df_rpnl[col] = pd.to_numeric(df_rpnl[col], errors="coerce")

            if "realized_pnl" in df_rpnl.columns:
                total_rpnl = df_rpnl["realized_pnl"].sum()
                colour = "normal" if total_rpnl >= 0 else "inverse"
                st.metric("Total Realized P&L", f"₹{total_rpnl:,.2f}", delta_color=colour)

            df_rpnl.columns = [c.replace("_", " ").title() for c in df_rpnl.columns]
            st.dataframe(df_rpnl, use_container_width=True)
        else:
            st.info("No realized P&L data yet — place and fill some orders first.")

    with tab3:
        ledger = fetch_ledger(account_id, limit=50)
        if ledger:
            df_ledger = pd.DataFrame(ledger)
            df_ledger.columns = [c.lower() for c in df_ledger.columns]
            if "amount" in df_ledger.columns:
                df_ledger["amount"] = pd.to_numeric(df_ledger["amount"], errors="coerce")
            show_cols = ["ledger_id", "entry_type", "amount", "value_date", "instrument_symbol", "trade_id", "created_at"]
            show_cols = [c for c in show_cols if c in df_ledger.columns]
            df_show = df_ledger[show_cols].copy()
            df_show.columns = [c.replace("_", " ").title() for c in df_show.columns]
            st.dataframe(df_show, use_container_width=True)
        else:
            st.info("No ledger entries for this account.")


# ===========================================================================
# Page 4 — Order History
# ===========================================================================
def page_order_history():
    st.header("📋 Order History")

    all_accounts = fetch_all_accounts()
    if not all_accounts:
        st.warning("No accounts available.")
        return

    acc_map = account_options(all_accounts)
    col1, col2 = st.columns(2)
    with col1:
        selected_acc_label = st.selectbox("Account", list(acc_map.keys()), key="oh_acc")
        account_id = acc_map[selected_acc_label]
    with col2:
        status_filter = st.selectbox(
            "Filter by Status",
            ["ALL", "OPEN", "PARTIAL", "FILLED", "CANCELLED"],
            key="oh_status",
        )

    orders = fetch_orders(account_id, status_filter)

    if not orders:
        st.info("No orders found for the selected filters.")
        return

    df_orders = pd.DataFrame(orders)
    df_orders.columns = [c.lower() for c in df_orders.columns]

    # Summary counts
    if "status" in df_orders.columns:
        counts = df_orders["status"].value_counts()
        cols = st.columns(len(counts))
        for i, (s, c) in enumerate(counts.items()):
            cols[i].metric(s, c)

    st.write(f"**{len(orders)} order(s) found**")

    # Render table with cancel buttons for OPEN / PARTIAL orders
    for _, row in df_orders.iterrows():
        with st.container():
            cols = st.columns([1, 1.3, 1, 1, 1, 1, 1, 1.4, 1])
            col_labels = ["Order ID", "Instrument", "Side", "Price", "Qty", "Filled", "Status", "Created", "Action"]
            inst_key = "instrument_symbol" if "instrument_symbol" in df_orders.columns else "instrument_id"
            data_keys = ["order_id", inst_key, "side", "price", "qty", "filled_qty", "status", "created_at"]

            for i, (label, key) in enumerate(zip(col_labels[:-1], data_keys)):
                val = row.get(key, "—")
                if key == "price":
                    try:
                        val = f"₹{float(val):,.2f}"
                    except (ValueError, TypeError):
                        pass
                elif key == "side":
                    val = f"🟢 {val}" if val == "BUY" else f"🔴 {val}"
                cols[i].write(f"**{label}**\n\n{val}")

            order_status = str(row.get("status", "")).upper()
            order_id_val = row.get("order_id")
            if order_status in ("OPEN", "PARTIAL") and order_id_val is not None:
                if cols[-1].button("❌ Cancel", key=f"cancel_{order_id_val}"):
                    result = api_delete(f"/orders/{order_id_val}")
                    if result is not None:
                        st.success(f"Order {order_id_val} cancelled.")
                        fetch_orders.clear()
                        fetch_order_book_depth.clear()
                        fetch_accounts.clear()
                        st.rerun()
            else:
                cols[-1].write(" ")

        st.divider()


# ===========================================================================
# Page 5 — Analytics
# ===========================================================================
def page_analytics():
    st.header("📈 Analytics")

    instruments = fetch_instruments()

    # --- Rolling 30-day Returns + Max Drawdown ---
    st.subheader("Rolling 30-Day Returns & Max Drawdown")
    if instruments:
        inst_map = instrument_options(instruments)
        selected_inst_label = st.selectbox(
            "Select Instrument", list(inst_map.keys()), key="an_inst"
        )
        instrument_id = inst_map[selected_inst_label]

        rolling = fetch_rolling_returns(instrument_id)
        if rolling:
            df_roll = pd.DataFrame(rolling)
            df_roll.columns = [c.lower() for c in df_roll.columns]
            for col in ["close", "rolling_30d_return_pct", "max_drawdown_pct", "rolling_30d_min", "rolling_30d_max"]:
                if col in df_roll.columns:
                    df_roll[col] = pd.to_numeric(df_roll[col], errors="coerce")

            date_col = "trade_date" if "trade_date" in df_roll.columns else df_roll.columns[0]
            ret_col = "rolling_30d_return_pct" if "rolling_30d_return_pct" in df_roll.columns else None
            dd_col = "max_drawdown_pct" if "max_drawdown_pct" in df_roll.columns else None

            if ret_col and df_roll[ret_col].dropna().empty:
                st.info(
                    "Need at least 31 trading days of price bars to compute 30-day rolling returns. "
                    "Run `python scripts/seed_prices.py` to generate 252 trading days."
                )
            else:
                tab_ret, tab_dd = st.tabs(["📈 Rolling Return", "📉 Max Drawdown"])
                with tab_ret:
                    if ret_col:
                        fig_roll = go.Figure()
                        fig_roll.add_trace(go.Scatter(
                            x=df_roll[date_col], y=df_roll[ret_col],
                            mode="lines", name="30-Day Rolling Return",
                            line=dict(color="royalblue", width=2),
                        ))
                        fig_roll.add_hline(y=0, line_dash="dash", line_color="gray")
                        fig_roll.update_layout(
                            title=f"Rolling 30-Day Return — {selected_inst_label}",
                            xaxis_title="Date", yaxis_title="Return (%)", height=400,
                        )
                        st.plotly_chart(fig_roll, use_container_width=True)
                with tab_dd:
                    if dd_col:
                        fig_dd = go.Figure()
                        fig_dd.add_trace(go.Scatter(
                            x=df_roll[date_col], y=df_roll[dd_col],
                            mode="lines", name="Max Drawdown",
                            fill="tozeroy",
                            line=dict(color="crimson", width=1.5),
                            fillcolor="rgba(220,20,60,0.15)",
                        ))
                        fig_dd.update_layout(
                            title=f"Rolling 30-Day Max Drawdown — {selected_inst_label}",
                            xaxis_title="Date", yaxis_title="Drawdown (%)", height=400,
                        )
                        st.plotly_chart(fig_dd, use_container_width=True)

                # Latest metrics
                latest_row = df_roll.dropna(subset=[ret_col] if ret_col else []).iloc[-1] if ret_col else None
                if latest_row is not None:
                    mc1, mc2 = st.columns(2)
                    mc1.metric("Latest 30-Day Return", f"{float(latest_row.get(ret_col, 0)):.2f}%")
                    if dd_col:
                        mc2.metric("Latest Max Drawdown", f"{float(latest_row.get(dd_col, 0)):.2f}%")
        else:
            st.info("No rolling returns data available for this instrument.")
    else:
        st.warning("No instruments available.")

    st.markdown("---")

    # --- Holdings > Cash ---
    st.subheader("Accounts Where Holdings Exceed Cash Balance")
    hvc = fetch_holdings_vs_cash()
    if hvc:
        df_hvc = pd.DataFrame(hvc)
        df_hvc.columns = [c.replace("_", " ").title() for c in df_hvc.columns]
        st.dataframe(df_hvc, use_container_width=True)
    else:
        st.info("No accounts where total holdings value exceeds cash balance.")

    st.markdown("---")

    # --- Bond YTM Calculator ---
    st.subheader("Bond Yield-to-Maturity (YTM) Calculator")
    bond_instruments = [i for i in instruments if str(i.get("instrument_type", "")).upper() == "BOND"]
    if bond_instruments:
        bond_map = instrument_options(bond_instruments)
        selected_bond_label = st.selectbox(
            "Select Bond Instrument", list(bond_map.keys()), key="an_bond"
        )
        bond_id = bond_map[selected_bond_label]

        if st.button("Calculate YTM", key="calc_ytm"):
            ytm_data = fetch_bond_ytm(bond_id)
            if ytm_data is not None and isinstance(ytm_data, dict):
                ytm_pct = ytm_data.get("ytm_pct")
                if ytm_pct is not None:
                    st.metric("Yield to Maturity (Approx.)", f"{float(ytm_pct):.4f}%")
                else:
                    ytm_val = ytm_data.get("ytm_approx") or ytm_data.get("ytm")
                    if ytm_val is not None:
                        st.metric("Yield to Maturity (Approx.)", f"{float(ytm_val):.4%}")
                    else:
                        st.warning("Bond may be expired or has no price data.")

                # Show bond details
                detail_keys = ["symbol", "name", "face_value", "coupon_rate", "maturity_date",
                               "latest_price", "market_price", "years_to_maturity", "annual_coupon"]
                details = {k: ytm_data[k] for k in detail_keys if k in ytm_data}
                if details:
                    st.json(details)
    else:
        st.info("No bond instruments available in the system.")


# ===========================================================================
# Main — Sidebar navigation
# ===========================================================================
def main():
    st.set_page_config(
        page_title="Paper-Trading Exchange",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.sidebar.title("📈 Paper-Trading Exchange")
    st.sidebar.markdown("---")

    pages = {
        "📊 Market Overview": page_market_overview,
        "🛒 Place Order": page_place_order,
        "💼 Portfolio": page_portfolio,
        "📋 Order History": page_order_history,
        "📈 Analytics": page_analytics,
    }

    selected_page = st.sidebar.radio(
        "Navigation",
        list(pages.keys()),
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")
    st.sidebar.caption(f"API: `{API_URL}`")

    pages[selected_page]()


if __name__ == "__main__":
    main()
