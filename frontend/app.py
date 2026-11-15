"""
Paper-Trading Exchange — Streamlit frontend ("PTX Terminal").

Pages
  • Market Overview  — quote, candlestick chart, order-book depth, VWAP, market watch
  • Place Order      — order ticket with live depth and pre-trade checks
  • Portfolio        — holdings, realized P&L, cash ledger, deposits
  • Order History    — order blotter with status filters and cancellation
  • Analytics        — rolling returns / drawdown, holdings-vs-cash, bond YTM

Every number on screen comes from the FastAPI backend (raw SQL on PostgreSQL);
this module is presentation only.
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import api
import ui
from ui import fmt_inr, fmt_num, fmt_pct, tone, esc

PAGES: dict = {}


# ===========================================================================
# Shared helpers
# ===========================================================================
def snap_to_tick(price: float, tick: float) -> float:
    tick = tick or 0.01
    return round(round(price / tick) * tick, 2)


def snapshot_row(instrument_id: int) -> dict:
    snap = api.fetch_market_snapshot()
    if snap.empty:
        return {}
    match = snap[snap["instrument_id"] == instrument_id]
    return match.iloc[0].to_dict() if not match.empty else {}


def instrument_picker(instruments, key: str, label: str = "Instrument", active_only: bool = False):
    """Instrument selectbox whose choice is shared across pages via `sel_iid`."""
    pool = [i for i in instruments if not active_only or str(i.get("status", "ACTIVE")).upper() == "ACTIVE"]
    if not pool:
        return None
    by_id = {i["instrument_id"]: i for i in pool}
    ids = list(by_id)
    default = next((i["instrument_id"] for i in pool if i["instrument_type"] == "STOCK"), ids[0])
    current = st.session_state.get("sel_iid", default)
    if current not in by_id:
        current = ids[0]

    def _sync():
        st.session_state["sel_iid"] = st.session_state[key]

    st.selectbox(
        label,
        ids,
        index=ids.index(current),
        format_func=lambda i: f"{by_id[i]['symbol']}  ·  {by_id[i]['name']}  ·  {by_id[i]['instrument_type']}",
        key=key,
        on_change=_sync,
    )
    st.session_state["sel_iid"] = st.session_state[key]
    return by_id[st.session_state[key]]


def best_prices(depth_rows):
    bids = [float(r["price"]) for r in depth_rows if r.get("side") == "BUY"]
    asks = [float(r["price"]) for r in depth_rows if r.get("side") == "SELL"]
    return (max(bids) if bids else None, min(asks) if asks else None)


def current_account():
    accounts = api.fetch_all_accounts()
    aid = st.session_state.get("account_id")
    return next((a for a in accounts if a["account_id"] == aid), None)


def account_label(a) -> str:
    if a is None:
        return "—"
    name = "House · Market Maker" if a.get("is_house") else a.get("user_name", "Account")
    return f"{name}  #{a['account_id']}"


def price_chart(bars: pd.DataFrame, n_bars: int, style: str, height: int = 540):
    """Candlestick / area chart with volume pane and 20/50-session SMAs."""
    df = bars.copy()
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df = df.tail(n_bars)
    up = df["close"] >= df["open"]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.03)
    if style == "Candles":
        fig.add_trace(
            go.Candlestick(
                x=df["trade_date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                name="OHLC",
                increasing=dict(line=dict(color=ui.UP, width=1), fillcolor=ui.UP),
                decreasing=dict(line=dict(color=ui.DOWN, width=1), fillcolor=ui.DOWN),
            ),
            row=1, col=1,
        )
    else:
        first, last = df["close"].iloc[0], df["close"].iloc[-1]
        colour = ui.UP if last >= first else ui.DOWN
        fill = "rgba(22,199,132,0.10)" if last >= first else "rgba(234,57,67,0.10)"
        fig.add_trace(
            go.Scatter(x=df["trade_date"], y=df["close"], name="Close", mode="lines",
                       line=dict(color=colour, width=2), fill="tozeroy", fillcolor=fill),
            row=1, col=1,
        )
        lo, hi = df["low"].min(), df["high"].max()
        pad = (hi - lo) * 0.08 or 1
        fig.update_yaxes(range=[lo - pad, hi + pad], row=1, col=1)

    if n_bars > 20:
        fig.add_trace(go.Scatter(x=df["trade_date"], y=df["sma20"], name="SMA 20", mode="lines",
                                 line=dict(color=ui.ACCENT, width=1.2)), row=1, col=1)
    if n_bars > 50:
        fig.add_trace(go.Scatter(x=df["trade_date"], y=df["sma50"], name="SMA 50", mode="lines",
                                 line=dict(color=ui.AMBER, width=1.2)), row=1, col=1)
    fig.add_trace(
        go.Bar(x=df["trade_date"], y=df["volume"], name="Volume", showlegend=False,
               marker_color=[("rgba(22,199,132,0.45)" if u else "rgba(234,57,67,0.45)") for u in up]),
        row=2, col=1,
    )
    fig.update_layout(height=height, xaxis_rangeslider_visible=False, bargap=0.15)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    fig.update_yaxes(tickformat=",.2f", row=1, col=1)
    fig.update_yaxes(tickformat="~s", row=2, col=1, showgrid=False)
    return fig


def depth_chart(depth_rows, height: int = 170):
    """Cumulative depth (uses the `cumulative_qty` running-sum window column)."""
    bids = sorted([r for r in depth_rows if r["side"] == "BUY"], key=lambda r: float(r["price"]), reverse=True)
    asks = sorted([r for r in depth_rows if r["side"] == "SELL"], key=lambda r: float(r["price"]))
    fig = go.Figure()
    if bids:
        fig.add_trace(go.Scatter(
            x=[float(r["price"]) for r in bids], y=[float(r["cumulative_qty"]) for r in bids],
            name="Bids", mode="lines", line=dict(color=ui.UP, shape="hv", width=1.6),
            fill="tozeroy", fillcolor="rgba(22,199,132,0.15)"))
    if asks:
        fig.add_trace(go.Scatter(
            x=[float(r["price"]) for r in asks], y=[float(r["cumulative_qty"]) for r in asks],
            name="Asks", mode="lines", line=dict(color=ui.DOWN, shape="hv", width=1.6),
            fill="tozeroy", fillcolor="rgba(234,57,67,0.15)"))
    fig.update_layout(height=height, showlegend=False, hovermode="closest", margin=dict(l=4, r=4, t=8, b=4))
    fig.update_xaxes(tickformat=",.2f", showspikes=False)
    fig.update_yaxes(title=None, showspikes=False)
    return fig


@st.fragment(run_every="5s")
def live_depth(instrument_id: int, levels: int = 8, show_chart: bool = False):
    depth = api.fetch_order_book_depth(instrument_id)
    ui.section_title("Order Book Depth", f"live · {datetime.now(ui.IST):%H:%M:%S}")
    ui.depth_ladder(depth, levels)
    if show_chart and depth:
        ui.chart(depth_chart(depth))


# ===========================================================================
# Page 1 — Market Overview
# ===========================================================================
def page_market_overview():
    instruments = api.fetch_instruments()
    if not instruments:
        ui.empty_state("No instruments listed.")
        return

    t1, t2, t3, t4, t5 = st.columns([2.6, 2.1, 1.7, 0.8, 0.8], vertical_alignment="bottom")
    with t1:
        inst = instrument_picker(instruments, "mo_inst", "Instrument")
    with t2:
        tf = st.radio("Range", ["1M", "3M", "6M", "1Y"], index=3, horizontal=True, key="mo_tf")
    with t3:
        style = st.radio("Chart", ["Candles", "Line"], horizontal=True, key="mo_style")
    tradable = str(inst.get("status", "ACTIVE")).upper() == "ACTIVE"
    with t4:
        if st.button("Buy", key="buy_mo", use_container_width=True, disabled=not tradable):
            st.session_state["trade_side"] = "BUY"
            st.switch_page(PAGES["trade"])
    with t5:
        if st.button("Sell", key="sell_mo", use_container_width=True, disabled=not tradable):
            st.session_state["trade_side"] = "SELL"
            st.switch_page(PAGES["trade"])

    iid = inst["instrument_id"]
    row = snapshot_row(iid) or dict(inst)
    bars = api.fetch_price_bars(iid, 252)
    vwap = api.fetch_vwap(iid)
    latest_vwap = float(vwap[-1]["vwap"]) if vwap else None

    left, right = st.columns([2.55, 1.45])
    with left:
        with ui.panel():
            if bars.empty:
                ui.quote_header(row, [])
                ui.empty_state("No price history for this instrument yet.")
            else:
                last = bars.iloc[-1]
                ui.quote_header(row, [
                    ("Open", fmt_num(last["open"])),
                    ("High", fmt_num(last["high"])),
                    ("Low", fmt_num(last["low"])),
                    ("Prev close", fmt_num(row.get("prev_close"))),
                    ("Volume", fmt_num(last["volume"], 0)),
                    ("52W high", fmt_num(row.get("high_52w"))),
                    ("52W low", fmt_num(row.get("low_52w"))),
                    ("VWAP", fmt_num(latest_vwap)),
                ])
                n = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252}[tf]
                ui.chart(price_chart(bars, n, style))
                st.caption(
                    f"OHLCV · {min(n, len(bars))} trading sessions · last bar "
                    f"{bars['trade_date'].iloc[-1]:%d %b %Y}"
                )

    with right:
        with ui.panel():
            live_depth(iid, levels=6, show_chart=True)
        with ui.panel():
            ui.section_title("VWAP", "volume-weighted average price per day")
            if vwap:
                rows = [
                    [pd.to_datetime(v["trade_date"]).strftime("%d %b %Y"), f'<b>{fmt_num(v["vwap"])}</b>',
                     fmt_num(v["total_volume"], 0), str(v["trade_count"])]
                    for v in reversed(vwap[-5:])
                ]
                ui.html_table(["Date", "VWAP", "Volume", "Trades"], rows)
            else:
                ui.empty_state("No trades yet — VWAP appears once orders match.")

    # --- Market watch ------------------------------------------------------
    with ui.panel():
        ui.section_title("Market Watch", "click a row to load it above")
        snap = api.fetch_market_snapshot()
        if snap.empty:
            ui.empty_state("No market data.")
            return
        watch = snap[["instrument_id", "symbol", "name", "instrument_type", "last", "change", "change_pct",
                      "volume", "high_52w", "low_52w", "trend"]].reset_index(drop=True)

        def _on_select():
            rows = st.session_state["watch"].selection.rows
            if rows:
                picked = int(watch.iloc[rows[0]]["instrument_id"])
                st.session_state["sel_iid"] = picked
                st.session_state["mo_inst"] = picked

        def colour(v):
            try:
                return f"color: {ui.UP}" if float(v) > 0 else f"color: {ui.DOWN}" if float(v) < 0 else ""
            except (TypeError, ValueError):
                return ""

        styled = (
            watch.drop(columns=["instrument_id"]).style
            .map(colour, subset=["change", "change_pct"])
            .format({"last": "{:,.2f}", "change": "{:+,.2f}", "change_pct": "{:+.2f}%", "volume": "{:,.0f}",
                     "high_52w": "{:,.2f}", "low_52w": "{:,.2f}"}, na_rep="—")
        )
        st.dataframe(
            styled,
            key="watch",
            on_select=_on_select,
            selection_mode="single-row",
            hide_index=True,
            use_container_width=True,
            column_config={
                "symbol": st.column_config.TextColumn("Symbol"),
                "name": st.column_config.TextColumn("Name", width="medium"),
                "instrument_type": st.column_config.TextColumn("Type", width="small"),
                "last": st.column_config.Column("LTP"),
                "change": st.column_config.Column("Chg"),
                "change_pct": st.column_config.Column("Chg %"),
                "volume": st.column_config.Column("Volume"),
                "high_52w": st.column_config.Column("52W High"),
                "low_52w": st.column_config.Column("52W Low"),
                "trend": st.column_config.LineChartColumn("30D Trend", width="medium"),
            },
        )


# ===========================================================================
# Page 2 — Place Order
# ===========================================================================
def _set_price(value: float):
    st.session_state["po_price"] = float(value)


def _set_side(side: str):
    st.session_state["trade_side"] = side


def page_place_order():
    instruments = api.fetch_instruments()
    account = current_account()
    if account is None:
        ui.empty_state("Select an account in the sidebar.")
        return

    ticket_col, info_col = st.columns([1.05, 1.6])

    with ticket_col:
        with ui.panel():
            ui.section_title("Order Ticket", "limit order · day")
            inst = instrument_picker(instruments, "po_inst", "Instrument", active_only=True)
            if inst is None:
                ui.empty_state("No active instruments available.")
                return
            iid = inst["instrument_id"]
            row = snapshot_row(iid)
            depth = api.fetch_order_book_depth(iid)
            best_bid, best_ask = best_prices(depth)
            tick = float(inst.get("tick_size") or 0.01)
            mult = float(inst.get("multiplier") or 1)
            ltp = row.get("last")

            # Pre-fill price with LTP when the instrument changes
            if "po_price" not in st.session_state or st.session_state.get("_px_iid") != iid:
                st.session_state["po_price"] = snap_to_tick(float(ltp), tick) if ltp else 100.0
                st.session_state["_px_iid"] = iid
            st.session_state.setdefault("po_qty", 1)
            side = st.session_state.get("trade_side", "BUY")

            s1, s2 = st.columns(2)
            with s1:
                st.button("BUY", key="buy_toggle" if side == "BUY" else "side_off_b",
                          on_click=_set_side, args=("BUY",), use_container_width=True)
            with s2:
                st.button("SELL", key="sell_toggle" if side == "SELL" else "side_off_s",
                          on_click=_set_side, args=("SELL",), use_container_width=True)

            p1, p2 = st.columns(2)
            with p1:
                price = st.number_input("Limit price (₹)", min_value=0.01, step=tick, format="%.2f", key="po_price")
            with p2:
                qty = st.number_input("Quantity", min_value=1, step=int(inst.get("lot_size") or 1), key="po_qty")

            q1, q2, q3 = st.columns(3)
            with q1:
                st.button(f"Bid {fmt_num(best_bid)}" if best_bid else "Bid —", key="qf_bid",
                          on_click=_set_price, args=(best_bid or 0,), disabled=best_bid is None,
                          use_container_width=True)
            with q2:
                st.button(f"LTP {fmt_num(ltp)}" if ltp else "LTP —", key="qf_ltp",
                          on_click=_set_price, args=(snap_to_tick(ltp, tick) if ltp else 0,),
                          disabled=not ltp, use_container_width=True)
            with q3:
                st.button(f"Ask {fmt_num(best_ask)}" if best_ask else "Ask —", key="qf_ask",
                          on_click=_set_price, args=(best_ask or 0,), disabled=best_ask is None,
                          use_container_width=True)

            # Pre-trade checks
            cash = float(account.get("cash_balance", 0))
            value = price * qty * mult
            portfolio = api.fetch_portfolio(account["account_id"])
            held = next((float(p["qty"]) for p in portfolio.get("positions", []) if p["instrument_id"] == iid), 0.0)
            if side == "BUY":
                ok = cash >= value
                check = ("Sufficient funds", "up") if ok else (f"Short by {fmt_inr(value - cash)}", "down")
                after = cash - value
            else:
                ok = held >= qty
                check = ("Covered by holdings", "up") if ok else (f"Exceeds holdings by {fmt_num(qty - held, 0)}", "down")
                after = cash + value
            mult_note = f" × {fmt_num(mult, 0)} multiplier" if mult != 1 else ""
            ui.html_table(
                ["Summary", ""],
                [
                    ["Order value", f"<b>{fmt_inr(value)}</b>"],
                    ["Calculation", f'<span class="muted">{fmt_num(qty, 0)} × {fmt_num(price)}{mult_note}</span>'],
                    ["Available cash", fmt_inr(cash)],
                    [f"Holdings in {esc(inst['symbol'])}", fmt_num(held, 0)],
                    ["Cash if fully filled", fmt_inr(after)],
                    ["Pre-trade check", f'<span class="{check[1]}">{check[0]}</span>'],
                ],
            )

            submit_key = "buy_submit" if side == "BUY" else "sell_submit"
            if st.button(f"{side} {qty:,} {inst['symbol']} @ ₹{price:,.2f}", key=submit_key,
                         type="primary", use_container_width=True):
                result = api.api_post("/orders", {
                    "account_id": account["account_id"], "instrument_id": iid,
                    "side": side, "price": price, "qty": int(qty),
                })
                if result is not None:
                    st.session_state["last_order"] = result
                    st.session_state["last_order_toast"] = True
                    api.clear_all_caches()
                    st.rerun()

        _render_last_order()
        bars = api.fetch_price_bars(iid, 252)
        if not bars.empty:
            with ui.panel():
                ui.section_title(f"{inst['symbol']} · 3 months")
                ui.chart(price_chart(bars, 63, "Line", height=260))

    with info_col:
        with ui.panel():
            last_bar = api.fetch_price_bars(iid, 1)
            stats = []
            if not last_bar.empty:
                lb = last_bar.iloc[-1]
                stats = [("Open", fmt_num(lb["open"])), ("High", fmt_num(lb["high"])), ("Low", fmt_num(lb["low"])),
                         ("Prev close", fmt_num(row.get("prev_close"))), ("Tick", fmt_num(tick)),
                         ("Lot", fmt_num(inst.get("lot_size") or 1, 0))]
            ui.quote_header(row or dict(inst), stats)
        with ui.panel():
            live_depth(iid, levels=8, show_chart=False)
        with ui.panel():
            ui.section_title(f"Your orders in {inst['symbol']}", account_label(account))
            orders = [o for o in api.fetch_orders(account["account_id"]) if o["instrument_id"] == iid][:8]
            if orders:
                ui.html_table(
                    ["Order", "Side", "Price", "Qty", "Filled", "Status", "Time"],
                    [[f"#{o['order_id']}", ui.side_pill(o["side"]), fmt_num(o["price"]), fmt_num(o["qty"], 0),
                      fmt_num(o["filled_qty"], 0), ui.status_pill(o["status"]),
                      pd.to_datetime(o["created_at"]).tz_convert(ui.IST).strftime("%d %b %H:%M:%S")]
                     for o in orders],
                )
            else:
                ui.empty_state("No orders in this instrument yet.")


def _render_last_order():
    res = st.session_state.get("last_order")
    if not res:
        return
    status = str(res.get("status", "—"))
    filled, qty = res.get("filled_qty", 0), res.get("qty", 0)
    if st.session_state.pop("last_order_toast", False):
        st.toast(f"Order #{res.get('order_id')} {status.lower()} · {filled}/{qty} filled", icon="✅")
    with ui.panel():
        h1, h2 = st.columns([2.4, 1], vertical_alignment="center")
        with h1:
            ui.section_title("Order confirmation", f"#{res.get('order_id')}")
        with h2:
            if st.button("Close", key="dismiss_last", icon=":material/close:", use_container_width=True):
                st.session_state.pop("last_order", None)
                st.rerun()
        msg = {
            "FILLED": "Fully executed.",
            "PARTIAL": "Partially executed — the remainder rests in the book.",
            "OPEN": "No matching liquidity — the order is resting in the book.",
        }.get(status, "")
        ui.html_table(
            ["Order", "Side", "Limit", "Filled", "Status"],
            [[f"#{res.get('order_id')} · {esc(res.get('instrument_symbol'))}", ui.side_pill(res.get("side")),
              fmt_num(res.get("price")), f"{fmt_num(filled, 0)} / {fmt_num(qty, 0)}", ui.status_pill(status)]],
        )
        if msg:
            st.caption(msg)
        fills = res.get("fills", [])
        if fills:
            ui.html_table(
                ["Fill", "Trade", "Qty", "Price", "Executed"],
                [[f"#{f['fill_seq']}", f"T{f['trade_id']}", fmt_num(f["qty"], 0), fmt_num(f["price"]),
                  pd.to_datetime(f["filled_at"]).tz_convert(ui.IST).strftime("%H:%M:%S")] for f in fills],
            )


# ===========================================================================
# Page 3 — Portfolio
# ===========================================================================
def page_portfolio():
    account = current_account()
    if account is None:
        ui.empty_state("Select an account in the sidebar.")
        return
    aid = account["account_id"]

    h1, h2 = st.columns([5, 1], vertical_alignment="bottom")
    with h1:
        ui.page_header("Portfolio", account_label(account))
    with h2:
        with st.popover("Add funds", icon=":material/add_card:", use_container_width=True):
            amt = st.number_input("Deposit amount (₹)", min_value=1.0, value=100000.0, step=10000.0,
                                  format="%.2f", key="dep_amount")
            if st.button("Deposit", key="dep_btn", type="primary", use_container_width=True):
                res = api.api_post(f"/accounts/{aid}/deposit", {"amount": amt})
                if res is not None:
                    api.clear_all_caches()
                    st.toast(f"Deposited {fmt_inr(amt)} · new balance {fmt_inr(res.get('new_cash_balance'))}", icon="💰")
                    st.rerun()

    data = api.fetch_portfolio(aid)
    positions = pd.DataFrame(data.get("positions", []))
    cash = float(data.get("cash_balance", account.get("cash_balance", 0)))
    realized = pd.DataFrame(api.fetch_realized_pnl(aid))

    if not positions.empty:
        for c in ["qty", "avg_cost", "latest_close", "market_value", "unrealized_pnl", "multiplier"]:
            positions[c] = pd.to_numeric(positions[c], errors="coerce")
        positions["invested"] = positions["avg_cost"] * positions["qty"] * positions["multiplier"]
        positions["pnl_pct"] = positions["unrealized_pnl"] / positions["invested"] * 100
    holdings = float(positions["market_value"].sum()) if not positions.empty else 0.0
    invested = float(positions["invested"].sum()) if not positions.empty else 0.0
    upnl = float(positions["unrealized_pnl"].sum()) if not positions.empty else 0.0
    rpnl = float(pd.to_numeric(realized["realized_pnl"]).sum()) if not realized.empty else 0.0
    net = holdings + cash

    ui.kpi_row([
        ("Net worth", fmt_inr(net), f"{fmt_pct(holdings / net * 100 if net else 0, sign=False)} invested", "muted"),
        ("Holdings value", fmt_inr(holdings), f"Cost {fmt_inr(invested)}", "muted"),
        ("Available cash", fmt_inr(cash), "Buying power", "muted"),
        ("Unrealized P&L", f'<span class="{tone(upnl)}">{fmt_inr(upnl, sign=True)}</span>',
         fmt_pct(upnl / invested * 100 if invested else 0), tone(upnl)),
        ("Net trade cash flow", f'<span class="{tone(rpnl)}">{fmt_inr(rpnl, sign=True)}</span>',
         "sell proceeds − buy cost", "muted"),
    ])

    tab1, tab2, tab3 = st.tabs(["Positions", "Realized P&L", "Cash Ledger"])

    with tab1:
        if positions.empty:
            ui.empty_state("No open positions. Place an order to get started.")
        else:
            with ui.panel():
                ui.section_title("Positions", f"{len(positions)} holdings · marked to latest close")
                rows = []
                for _, p in positions.sort_values("market_value", ascending=False).iterrows():
                    t = tone(p["unrealized_pnl"])
                    rows.append([
                        f'<b>{esc(p["symbol"])}</b>{ui.type_badge(p["instrument_type"])}'
                        f'<div class="muted" style="font-size:.75rem">{esc(p["name"])}</div>',
                        fmt_num(p["qty"], 0), fmt_num(p["avg_cost"]), fmt_num(p["latest_close"]),
                        fmt_inr(p["invested"]), fmt_inr(p["market_value"]),
                        f'<span class="{t}">{fmt_inr(p["unrealized_pnl"], sign=True)}</span>',
                        f'<span class="{t}">{fmt_pct(p["pnl_pct"])}</span>',
                        fmt_pct(p["market_value"] / holdings * 100 if holdings else 0, sign=False),
                    ])
                ui.html_table(["Instrument", "Qty", "Avg cost", "LTP", "Invested", "Current value", "Unrealized P&L",
                               "P&L %", "Weight"], rows)

            def donut(labels, values, colors=None):
                fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.64, sort=False, textinfo="none",
                                       marker=dict(colors=colors, line=dict(color=ui.PANEL, width=2)),
                                       hovertemplate="%{label}<br>₹%{value:,.2f}<br>%{percent}<extra></extra>"))
                fig.update_layout(height=240, margin=dict(l=0, r=0, t=0, b=0), hovermode="closest",
                                  legend=dict(orientation="v", x=1.0, y=0.5, yanchor="middle", font=dict(size=12)),
                                  annotations=[dict(text=f"<b>{ui.fmt_compact(sum(values))}</b>", showarrow=False,
                                                    font=dict(size=15, color=ui.TEXT))])
                return fig

            a1, a2 = st.columns(2)
            with a1:
                with ui.panel():
                    ui.section_title("Allocation by holding")
                    alloc = positions.groupby("symbol")["market_value"].sum().sort_values(ascending=False)
                    ui.chart(donut(list(alloc.index), list(alloc.values)))
            with a2:
                with ui.panel():
                    ui.section_title("Allocation by asset class", "incl. cash")
                    by_type = positions.groupby("instrument_type")["market_value"].sum()
                    labels = list(by_type.index) + ["CASH"]
                    values = list(by_type.values) + [cash]
                    colors = [ui.TYPE_COLORS.get(t, ui.MUTED) for t in by_type.index] + ["#334155"]
                    ui.chart(donut(labels, values, colors))

    with tab2:
        if realized.empty:
            ui.empty_state("No executed trades yet — realized P&L appears after fills.")
        else:
            for c in ["total_buy_cost", "total_sell_proceeds", "realized_pnl", "total_qty_traded", "trade_count"]:
                realized[c] = pd.to_numeric(realized[c], errors="coerce")
            rc, cc = st.columns([1.6, 1])
            with rc:
                with ui.panel():
                    ui.section_title("Realized P&L by instrument", "sell proceeds − buy cost from matched fills")
                    ui.html_table(
                        ["Instrument", "Buy cost", "Sell proceeds", "Net", "Qty traded", "Trades"],
                        [[f'<b>{esc(r["symbol"])}</b>{ui.type_badge(r["instrument_type"])}',
                          fmt_inr(r["total_buy_cost"]), fmt_inr(r["total_sell_proceeds"]),
                          f'<span class="{tone(r["realized_pnl"])}">{fmt_inr(r["realized_pnl"], sign=True)}</span>',
                          fmt_num(r["total_qty_traded"], 0), fmt_num(r["trade_count"], 0)]
                         for _, r in realized.iterrows()],
                    )
            with cc:
                with ui.panel():
                    ui.section_title("Net by instrument")
                    fig = go.Figure(go.Bar(
                        x=realized["realized_pnl"], y=realized["symbol"], orientation="h",
                        marker_color=[ui.UP if v >= 0 else ui.DOWN for v in realized["realized_pnl"]],
                        hovertemplate="%{y}: ₹%{x:,.2f}<extra></extra>"))
                    fig.update_layout(height=max(160, 46 * len(realized)), hovermode="closest",
                                      margin=dict(l=0, r=0, t=4, b=0))
                    fig.update_xaxes(tickformat="~s", showspikes=False)
                    fig.update_yaxes(side="left", autorange="reversed", showspikes=False)
                    ui.chart(fig)

    with tab3:
        ledger = api.fetch_ledger(aid, 100)
        with ui.panel():
            ui.section_title("Cash Ledger", "latest 100 entries")
            if not ledger:
                ui.empty_state("No ledger entries for this account.")
            else:
                rows = []
                for e in ledger:
                    amt = float(e["amount"])
                    et = str(e["entry_type"]).upper()
                    cls = "buy" if et in ("DEPOSIT", "SELL", "COUPON") else "sell" if et in ("BUY", "WITHDRAWAL") else "neutral"
                    rows.append([
                        pd.to_datetime(e["created_at"]).tz_convert(ui.IST).strftime("%d %b %Y, %H:%M"),
                        f'<span class="pill {cls}">{esc(et)}</span>',
                        esc(e.get("instrument_symbol") or "—"),
                        f"T{e['trade_id']}" if e.get("trade_id") else "—",
                        str(e["value_date"]),
                        f'<span class="{tone(amt)}">{fmt_inr(amt, sign=True)}</span>',
                    ])
                ui.html_table(["Timestamp (IST)", "Type", "Instrument", "Trade", "Value date", "Amount"], rows,
                              align_left=2)


# ===========================================================================
# Page 4 — Order History
# ===========================================================================
def page_order_history():
    account = current_account()
    if account is None:
        ui.empty_state("Select an account in the sidebar.")
        return
    aid = account["account_id"]
    ui.page_header("Order History", account_label(account))

    all_orders = api.fetch_orders(aid, "ALL")
    counts = pd.Series([o["status"] for o in all_orders]).value_counts().to_dict() if all_orders else {}
    total = len(all_orders)
    filled_orders = counts.get("FILLED", 0)
    ui.kpi_row([
        ("Total orders", fmt_num(total, 0), "all time", "muted"),
        ("Working", fmt_num(counts.get("OPEN", 0) + counts.get("PARTIAL", 0), 0),
         f"{counts.get('OPEN', 0)} open · {counts.get('PARTIAL', 0)} partial", "muted"),
        ("Filled", fmt_num(filled_orders, 0), f"{fmt_pct(filled_orders / total * 100 if total else 0, sign=False)} fill rate", "up"),
        ("Cancelled", fmt_num(counts.get("CANCELLED", 0), 0), "", "muted"),
    ])

    statuses = ["ALL", "OPEN", "PARTIAL", "FILLED", "CANCELLED"]
    status_filter = st.radio(
        "Status", statuses, horizontal=True, key="oh_status", label_visibility="collapsed",
        format_func=lambda s: f"{s.title()}  ({total if s == 'ALL' else counts.get(s, 0)})",
    )
    orders = all_orders if status_filter == "ALL" else api.fetch_orders(aid, status_filter)

    with ui.panel():
        if not orders:
            ui.empty_state("No orders match this filter.")
            return
        df = pd.DataFrame(orders)
        df["created_at"] = pd.to_datetime(df["created_at"]).dt.tz_convert(ui.IST).dt.tz_localize(None)
        for c in ["price", "qty", "filled_qty"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["fill_pct"] = (df["filled_qty"] / df["qty"] * 100).round(1)
        df["value"] = df["price"] * df["qty"]
        view = df[["order_id", "created_at", "instrument_symbol", "side", "price", "qty", "filled_qty", "fill_pct",
                   "value", "status"]]

        def side_c(v):
            return f"color: {ui.UP}; font-weight:600" if v == "BUY" else f"color: {ui.DOWN}; font-weight:600"

        def status_c(v):
            return {"FILLED": f"color: {ui.UP}", "CANCELLED": f"color: {ui.DOWN}", "PARTIAL": f"color: {ui.AMBER}",
                    "OPEN": "color: #7fb0ff"}.get(v, "")

        styled = (view.style.map(side_c, subset=["side"]).map(status_c, subset=["status"])
                  .format({"price": "{:,.2f}", "qty": "{:,.0f}", "filled_qty": "{:,.0f}", "value": "{:,.2f}"}))
        ui.section_title("Order blotter", "select working orders to cancel them")
        event = st.dataframe(
            styled,
            key="blotter",
            on_select="rerun",
            selection_mode="multi-row",
            hide_index=True,
            use_container_width=True,
            height=min(38 + 35 * len(view), 560),
            column_config={
                "order_id": st.column_config.NumberColumn("Order #", format="%d", width="small"),
                "created_at": st.column_config.DatetimeColumn("Time (IST)", format="DD MMM YYYY, HH:mm:ss"),
                "instrument_symbol": st.column_config.TextColumn("Instrument"),
                "side": st.column_config.TextColumn("Side", width="small"),
                "price": st.column_config.Column("Limit price"),
                "qty": st.column_config.Column("Qty", width="small"),
                "filled_qty": st.column_config.Column("Filled", width="small"),
                "fill_pct": st.column_config.ProgressColumn("Fill", format="%.0f%%", min_value=0, max_value=100),
                "value": st.column_config.Column("Notional"),
                "status": st.column_config.TextColumn("Status", width="small"),
            },
        )

        selected = view.iloc[event.selection.rows] if event.selection.rows else view.iloc[0:0]
        cancellable = selected[selected["status"].isin(["OPEN", "PARTIAL"])]
        b1, b2 = st.columns([1, 3], vertical_alignment="center")
        with b1:
            clicked = st.button(
                f"Cancel {len(cancellable)} order(s)" if len(cancellable) else "Cancel selected",
                key="sell_cancel" if len(cancellable) else "side_off_cancel",
                disabled=cancellable.empty, use_container_width=True, icon=":material/cancel:",
            )
        with b2:
            if len(selected) and cancellable.empty:
                st.caption("Only OPEN or PARTIAL orders can be cancelled.")
            elif len(selected) > len(cancellable):
                st.caption(f"{len(selected) - len(cancellable)} selected order(s) are already final and will be skipped.")
        if clicked:
            done = 0
            for oid in cancellable["order_id"]:
                if api.api_delete(f"/orders/{int(oid)}") is not None:
                    done += 1
            api.clear_all_caches()
            st.toast(f"Cancelled {done} order(s)", icon="🛑")
            st.rerun()


# ===========================================================================
# Page 5 — Analytics
# ===========================================================================
def page_analytics():
    ui.page_header("Analytics", "Window-function analytics computed in PostgreSQL")
    instruments = api.fetch_instruments()
    if not instruments:
        ui.empty_state("No instruments available.")
        return

    c1, _ = st.columns([2, 3])
    with c1:
        inst = instrument_picker(instruments, "an_inst", "Instrument")
    iid = inst["instrument_id"]

    roll = pd.DataFrame(api.fetch_rolling_returns(iid))
    if roll.empty:
        ui.empty_state("No price history for this instrument.")
    else:
        roll["trade_date"] = pd.to_datetime(roll["trade_date"])
        for c in ["close", "rolling_30d_return_pct", "max_drawdown_pct", "rolling_30d_min", "rolling_30d_max"]:
            roll[c] = pd.to_numeric(roll[c], errors="coerce")
        valid = roll.dropna(subset=["rolling_30d_return_pct"])
        if valid.empty:
            st.info(
                "At least 31 trading days of price bars are needed for 30-day rolling returns. "
                "Run `scripts/seed_prices.py` to generate 252 trading days.",
                icon=":material/info:",
            )
        else:
            latest = valid.iloc[-1]
            period_ret = (roll["close"].iloc[-1] / roll["close"].iloc[0] - 1) * 100
            ui.kpi_row([
                ("30-day return", f'<span class="{tone(latest["rolling_30d_return_pct"])}">'
                                  f'{fmt_pct(latest["rolling_30d_return_pct"])}</span>',
                 f"vs {fmt_num(latest['close_30d_ago'])} 30 sessions ago", "muted"),
                ("Max drawdown (30D)", f'<span class="down">{fmt_pct(latest["max_drawdown_pct"])}</span>',
                 "worst peak-to-trough in window", "muted"),
                ("30D high / low", f'{fmt_num(latest["rolling_30d_max"])}',
                 f"low {fmt_num(latest['rolling_30d_min'])}", "muted"),
                (f"Period return ({len(roll)} sessions)", f'<span class="{tone(period_ret)}">{fmt_pct(period_ret)}</span>',
                 f"{fmt_num(roll['close'].iloc[0])} → {fmt_num(roll['close'].iloc[-1])}", "muted"),
            ])

            with ui.panel():
                t1, t2, t3 = st.tabs(["Rolling 30-day return", "Max drawdown", "30-day price channel"])
                with t1:
                    y = valid["rolling_30d_return_pct"]
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=valid["trade_date"], y=y.where(y >= 0, 0), mode="lines", name="Gain",
                                             line=dict(color=ui.UP, width=1.5), fill="tozeroy",
                                             fillcolor="rgba(22,199,132,0.15)"))
                    fig.add_trace(go.Scatter(x=valid["trade_date"], y=y.where(y < 0, 0), mode="lines", name="Loss",
                                             line=dict(color=ui.DOWN, width=1.5), fill="tozeroy",
                                             fillcolor="rgba(234,57,67,0.15)"))
                    fig.update_layout(height=380, showlegend=False)
                    fig.update_yaxes(ticksuffix="%")
                    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                    ui.chart(fig)
                with t2:
                    fig = go.Figure(go.Scatter(x=roll["trade_date"], y=roll["max_drawdown_pct"], mode="lines",
                                               name="Max drawdown", line=dict(color=ui.DOWN, width=1.5),
                                               fill="tozeroy", fillcolor="rgba(234,57,67,0.15)"))
                    fig.update_layout(height=380, showlegend=False)
                    fig.update_yaxes(ticksuffix="%")
                    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                    ui.chart(fig)
                with t3:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=roll["trade_date"], y=roll["rolling_30d_max"], mode="lines",
                                             name="30D high", line=dict(color="rgba(59,130,246,0.5)", width=1)))
                    fig.add_trace(go.Scatter(x=roll["trade_date"], y=roll["rolling_30d_min"], mode="lines",
                                             name="30D low", line=dict(color="rgba(59,130,246,0.5)", width=1),
                                             fill="tonexty", fillcolor="rgba(59,130,246,0.08)"))
                    fig.add_trace(go.Scatter(x=roll["trade_date"], y=roll["close"], mode="lines", name="Close",
                                             line=dict(color=ui.TEXT, width=1.6)))
                    fig.update_layout(height=380)
                    fig.update_yaxes(tickformat=",.2f")
                    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                    ui.chart(fig)

    left, right = st.columns([1.5, 1])
    with left:
        with ui.panel():
            ui.section_title("Accounts where holdings exceed cash", "lateral correlated subquery")
            hvc = api.fetch_holdings_vs_cash()
            if hvc:
                ui.html_table(
                    ["Account", "Cash", "Holdings", "Excess over cash"],
                    [[f'<b>{esc(h["user_name"])}</b> <span class="muted">#{h["account_id"]}</span>',
                      fmt_inr(h["cash_balance"]), fmt_inr(h["total_holdings_value"]),
                      f'<span class="up">{fmt_inr(h["excess_over_cash"], sign=True)}</span>'] for h in hvc],
                )
            else:
                ui.empty_state("No client account currently holds more in securities than in cash.")

    with right:
        with ui.panel():
            ui.section_title("Bond Yield-to-Maturity", "approximation formula")
            bonds = [i for i in instruments if str(i.get("instrument_type", "")).upper() == "BOND"]
            if not bonds:
                ui.empty_state("No bond instruments listed.")
            else:
                bmap = {b["instrument_id"]: b for b in bonds}
                bid = st.selectbox("Bond", list(bmap), key="an_bond",
                                   format_func=lambda i: f"{bmap[i]['symbol']} · {bmap[i]['name']}")
                y = api.fetch_bond_ytm(bid)
                if y:
                    ytm = y.get("ytm_pct")
                    html = (
                        f'<div class="kpi" style="margin-bottom:.6rem"><div class="k">Yield to maturity</div>'
                        f'<div class="v">{fmt_num(ytm, 3) + "%" if ytm is not None else "—"}</div>'
                        f'<div class="d">Coupon {fmt_pct(float(y["coupon_rate"]) * 100, sign=False)} · '
                        f'matures {esc(y.get("maturity_date"))}</div></div>'
                    )
                    ui.html_block(html)
                    ui.html_table(["Term", "Value"], [
                        ["Face value", fmt_inr(y.get("face_value"))],
                        ["Clean price (quoted)", fmt_num(y.get("latest_price"))],
                        ["Market price (× multiplier)", fmt_inr(y.get("market_price"))],
                        ["Annual coupon", fmt_inr(y.get("annual_coupon"))],
                        ["Coupon frequency", f'{esc(y.get("coupon_frequency"))}× / year'],
                        ["Years to maturity", fmt_num(y.get("years_to_maturity"), 2)],
                        ["Price date", esc(y.get("price_date"))],
                    ])
                    if ytm is None:
                        st.caption("Bond has matured or has no price data.")


# ===========================================================================
# Shell — navigation, sidebar, app bar
# ===========================================================================
def sidebar():
    with st.sidebar:
        accounts = api.fetch_all_accounts()
        if not accounts:
            return
        ids = [a["account_id"] for a in accounts]
        by_id = {a["account_id"]: a for a in accounts}
        if st.session_state.get("account_id") not in by_id:
            st.session_state["account_id"] = next((a["account_id"] for a in accounts if not a.get("is_house")), ids[0])
        st.markdown("&nbsp;", unsafe_allow_html=True)
        st.selectbox("Trading account", ids, key="account_id", format_func=lambda i: account_label(by_id[i]))
        acct = by_id[st.session_state["account_id"]]
        ui.html_block(f"""
        <div class="kpi" style="padding:.7rem .85rem">
          <div class="k">Available cash</div>
          <div class="v" style="font-size:1.15rem">{fmt_inr(acct.get("cash_balance"))}</div>
          <div class="d">{esc(acct.get("user_email", ""))}</div>
        </div>
        """)
        if acct.get("is_house"):
            st.caption("House account provides liquidity — use it to post SELL orders for demos.")
        st.markdown("<br>", unsafe_allow_html=True)
        st.caption(f"API · `{api.API_URL}`  \nPostgreSQL 16 · FastAPI · Streamlit")


def main():
    st.set_page_config(page_title="PTX Terminal · Paper Trading Exchange", page_icon="📈", layout="wide",
                       initial_sidebar_state="expanded")
    ui.inject_css()
    ui.register_plotly_theme()

    PAGES["market"] = st.Page(page_market_overview, title="Market Overview", icon=":material/candlestick_chart:",
                              url_path="markets", default=True)
    PAGES["trade"] = st.Page(page_place_order, title="Place Order", icon=":material/swap_horiz:", url_path="trade")
    PAGES["portfolio"] = st.Page(page_portfolio, title="Portfolio", icon=":material/account_balance_wallet:",
                                 url_path="portfolio")
    PAGES["orders"] = st.Page(page_order_history, title="Order History", icon=":material/receipt_long:",
                              url_path="orders")
    PAGES["analytics"] = st.Page(page_analytics, title="Analytics", icon=":material/insights:", url_path="analytics")
    nav = st.navigation({
        "Trade": [PAGES["market"], PAGES["trade"]],
        "Account": [PAGES["portfolio"], PAGES["orders"]],
        "Research": [PAGES["analytics"]],
    })

    api_ok = api.fetch_health()
    if api_ok:
        sidebar()
    ui.app_bar(api_ok, account_label(current_account()) if api_ok else None)
    if not api_ok:
        st.error(f"The exchange API at `{api.API_URL}` is not reachable. Start the backend "
                 "(`docker compose up -d`) and refresh.", icon=":material/cloud_off:")
        st.stop()
    ui.ticker_tape(api.fetch_market_snapshot())
    nav.run()


if __name__ == "__main__":
    main()
