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
    return api_get("/accounts") or []


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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def instrument_options(instruments):
    """Return (label→id) mapping from instrument list."""
    return {f"{i['symbol']} — {i['name']}": i["instrument_id"] for i in instruments}


def account_options(accounts):
    """Return (label→id) mapping from account list."""
    return {
        f"{a.get('user_name', 'Account')} (#{a['account_id']} — Cash: ₹{float(a.get('cash_balance', 0)):,.2f})": a["account_id"]
        for a in accounts
    }


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
        # Normalise column names to lower-case
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
    else:
        st.info("No price bar data available for this instrument.")

    # --- Order book depth ---
    st.subheader("Order Book Depth")
    depth = fetch_order_book_depth(instrument_id)
    if depth:
        df_depth = pd.DataFrame(depth)
        df_depth.columns = [c.replace("_", " ").title() for c in df_depth.columns]
        st.dataframe(df_depth, use_container_width=True)
    else:
        st.info("No open orders in the order book for this instrument.")

    # --- VWAP ---
    st.subheader("VWAP")
    vwap_data = fetch_vwap(instrument_id)
    if vwap_data is not None:
        if isinstance(vwap_data, list):
            df_vwap = pd.DataFrame(vwap_data)
            df_vwap.columns = [c.replace("_", " ").title() for c in df_vwap.columns]
            st.dataframe(df_vwap, use_container_width=True)
        elif isinstance(vwap_data, dict):
            vwap_val = vwap_data.get("vwap") or vwap_data.get("value")
            if vwap_val is not None:
                st.metric("VWAP", f"₹{float(vwap_val):,.4f}")
            else:
                st.json(vwap_data)
        else:
            st.metric("VWAP", f"₹{float(vwap_data):,.4f}")
    else:
        st.info("VWAP data not available.")


# ===========================================================================
# Page 2 — Place Order
# ===========================================================================
def page_place_order():
    st.header("🛒 Place Order")

    accounts = fetch_accounts()
    instruments = fetch_instruments()

    if not accounts:
        st.warning("No accounts available.")
        return
    if not instruments:
        st.warning("No instruments available.")
        return

    acc_map = account_options(accounts)
    inst_map = instrument_options(instruments)

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

    st.write(f"**Order Value:** ₹{price * qty:,.2f}")

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
            st.success("✅ Order placed successfully!")
            order_id = result.get("order_id", result.get("id", "—"))
            status = result.get("status", "—")
            filled_qty = result.get("filled_qty", 0)
            st.markdown(
                f"""
                | Field | Value |
                |---|---|
                | **Order ID** | {order_id} |
                | **Status** | {status} |
                | **Filled Qty** | {filled_qty} / {qty} |
                | **Side** | {side} |
                | **Price** | ₹{price:,.2f} |
                """
            )
            fills = result.get("fills", [])
            if fills:
                st.subheader("Trade Fills")
                st.dataframe(pd.DataFrame(fills), use_container_width=True)
            # Clear cached data so portfolio/orders/accounts/depth refresh
            fetch_orders.clear()
            fetch_portfolio.clear()
            fetch_realized_pnl.clear()
            fetch_accounts.clear()
            fetch_order_book_depth.clear()
            fetch_vwap.clear()
            fetch_holdings_vs_cash.clear()


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

    # Cash balance
    selected_acc = next(
        (a for a in accounts if a["account_id"] == account_id), None
    )
    if selected_acc:
        cash = selected_acc.get("cash_balance", 0)
        st.metric("💰 Cash Balance", f"₹{float(cash):,.2f}")

    # Portfolio positions
    st.subheader("Positions")
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

        # Rename columns for display (backend returns latest_close; accept current_price too)
        col_rename = {
            "symbol": "Symbol",
            "qty": "Qty",
            "avg_cost": "Avg Cost (₹)",
            "latest_close": "Current Price (₹)",
            "current_price": "Current Price (₹)",
            "market_value": "Market Value (₹)",
            "unrealized_pnl": "Unrealized P&L (₹)",
            "instrument_type": "Type",
        }
        display_cols = [c for c in col_rename if c in df_pos.columns]
        df_display = df_pos[display_cols].rename(columns=col_rename)

        # Colour unrealized P&L
        def style_pnl(val):
            try:
                colour = "green" if float(val) >= 0 else "red"
                return f"color: {colour}"
            except (ValueError, TypeError):
                return ""

        pnl_col = "Unrealized P&L (₹)"
        if pnl_col in df_display.columns:
            st.dataframe(
                df_display.style.applymap(style_pnl, subset=[pnl_col]),
                use_container_width=True,
            )
        else:
            st.dataframe(df_display, use_container_width=True)

        # Pie chart — portfolio allocation by instrument type
        if "instrument_type" in df_pos.columns and "market_value" in df_pos.columns:
            st.subheader("Portfolio Allocation by Instrument Type")
            alloc = (
                df_pos.groupby("instrument_type")["market_value"]
                .sum()
                .reset_index()
            )
            alloc.columns = ["Type", "Market Value (₹)"]
            fig_pie = px.pie(
                alloc,
                names="Type",
                values="Market Value (₹)",
                title="Portfolio Allocation",
                hole=0.35,
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        elif "symbol" in df_pos.columns and "market_value" in df_pos.columns:
            # Fallback: by symbol
            st.subheader("Portfolio Allocation by Symbol")
            fig_pie = px.pie(
                df_pos,
                names="symbol",
                values="market_value",
                title="Portfolio Allocation",
                hole=0.35,
            )
            st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("No positions held in this account.")

    # Realized P&L
    st.subheader("Realized P&L")
    realized = fetch_realized_pnl(account_id)
    if realized:
        df_rpnl = pd.DataFrame(realized)
        df_rpnl.columns = [c.replace("_", " ").title() for c in df_rpnl.columns]
        st.dataframe(df_rpnl, use_container_width=True)
    else:
        st.info("No realized P&L data available.")


# ===========================================================================
# Page 4 — Order History
# ===========================================================================
def page_order_history():
    st.header("📋 Order History")

    accounts = fetch_accounts()
    if not accounts:
        st.warning("No accounts available.")
        return

    acc_map = account_options(accounts)
    col1, col2 = st.columns(2)
    with col1:
        selected_acc_label = st.selectbox("Account", list(acc_map.keys()), key="oh_acc")
        account_id = acc_map[selected_acc_label]
    with col2:
        status_filter = st.selectbox(
            "Filter by Status",
            ["ALL", "OPEN", "FILLED", "PARTIAL", "CANCELLED"],
            key="oh_status",
        )

    orders = fetch_orders(account_id, status_filter)

    if not orders:
        st.info("No orders found for the selected filters.")
        return

    df_orders = pd.DataFrame(orders)
    df_orders.columns = [c.lower() for c in df_orders.columns]

    # Display columns selection
    display_cols = [
        c for c in [
            "order_id", "instrument_id", "side", "price", "qty",
            "filled_qty", "status", "created_at",
        ]
        if c in df_orders.columns
    ]

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
                if key in ("price",):
                    try:
                        val = f"₹{float(val):,.2f}"
                    except (ValueError, TypeError):
                        pass
                cols[i].write(f"**{label}**\n\n{val}")

            # Cancel button for OPEN or PARTIAL orders
            order_status = str(row.get("status", "")).upper()
            order_id_val = row.get("order_id")
            if order_status in ("OPEN", "PARTIAL") and order_id_val is not None:
                if cols[-1].button("❌ Cancel", key=f"cancel_{order_id_val}"):
                    result = api_delete(f"/orders/{order_id_val}")
                    if result is not None:
                        st.success(f"Order {order_id_val} cancelled.")
                        fetch_orders.clear()
                        fetch_order_book_depth.clear()
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

    # --- Rolling 30-day Returns ---
    st.subheader("Rolling 30-Day Returns")
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
            date_col = next(
                (c for c in df_roll.columns if "date" in c or "day" in c), df_roll.columns[0]
            )
            ret_col = next(
                (c for c in df_roll.columns if "return" in c or "ret" in c),
                df_roll.columns[1] if len(df_roll.columns) > 1 else df_roll.columns[0],
            )
            df_roll[ret_col] = pd.to_numeric(df_roll[ret_col], errors="coerce")
            if df_roll[ret_col].dropna().empty:
                st.info(
                    "Need at least 31 trading days of price bars to compute 30-day rolling returns. "
                    "Run `python scripts/seed_prices.py` to generate 252 trading days."
                )
            else:
                fig_roll = go.Figure()
                fig_roll.add_trace(
                    go.Scatter(
                        x=df_roll[date_col],
                        y=df_roll[ret_col],
                        mode="lines",
                        name="30-Day Rolling Return",
                        line=dict(color="royalblue", width=2),
                    )
                )
                fig_roll.add_hline(y=0, line_dash="dash", line_color="gray")
                fig_roll.update_layout(
                    title=f"Rolling 30-Day Return — {selected_inst_label}",
                    xaxis_title="Date",
                    yaxis_title="Return (%)",
                    height=400,
                )
                st.plotly_chart(fig_roll, use_container_width=True)
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
        st.info("No accounts found where total holdings value exceeds cash balance.")

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
            if ytm_data is not None:
                if isinstance(ytm_data, dict):
                    ytm_pct = ytm_data.get("ytm_pct")
                    ytm_val = ytm_data.get("ytm_approx") or ytm_data.get("ytm") or ytm_data.get("yield_to_maturity")
                    if ytm_pct is not None:
                        st.metric("Yield to Maturity (Approx.)", f"{float(ytm_pct):.4f}%")
                    elif ytm_val is not None:
                        st.metric("Yield to Maturity (Approx.)", f"{float(ytm_val):.4%}")
                    extra_keys = {k: v for k, v in ytm_data.items() if k not in ("ytm", "yield_to_maturity", "ytm_approx", "ytm_pct")}
                    if extra_keys:
                        st.json(extra_keys)
                else:
                    st.metric("Yield to Maturity", f"{float(ytm_data):.4%}")
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
