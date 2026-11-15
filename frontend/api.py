"""
Thin REST client for the FastAPI backend plus cached fetch helpers.

All network access from the Streamlit UI goes through this module so the
pages never talk to `requests` directly.
"""

import os

import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Low-level request helpers
# ---------------------------------------------------------------------------
def _error_detail(exc: requests.exceptions.HTTPError) -> str:
    try:
        return exc.response.json().get("detail", str(exc))
    except Exception:
        return str(exc)


def _request(method: str, path: str, *, params=None, payload=None, quiet=False):
    """Perform a request; returns parsed JSON or None (and shows a toast/error)."""
    try:
        resp = requests.request(
            method, f"{API_URL}{path}", params=params, json=payload, timeout=10
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as exc:
        if not quiet:
            st.error(f"**Request rejected** — {_error_detail(exc)}", icon=":material/error:")
        return None
    except requests.exceptions.RequestException as exc:
        if not quiet:
            st.error(
                f"**Cannot reach the exchange API** at `{API_URL}` — {exc}",
                icon=":material/cloud_off:",
            )
        return None


def api_get(path: str, params: dict = None, quiet: bool = False):
    return _request("GET", path, params=params, quiet=quiet)


def api_post(path: str, payload: dict):
    return _request("POST", path, payload=payload)


def api_delete(path: str):
    return _request("DELETE", path)


# ---------------------------------------------------------------------------
# Cached fetchers (short TTL so trading activity propagates quickly)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=5, show_spinner=False)
def fetch_health() -> bool:
    return api_get("/", quiet=True) is not None


@st.cache_data(ttl=5, show_spinner=False)
def fetch_instruments():
    return api_get("/instruments") or []


@st.cache_data(ttl=60, show_spinner=False)
def fetch_instrument_detail(instrument_id: int):
    return api_get(f"/instruments/{instrument_id}", quiet=True) or {}


@st.cache_data(ttl=5, show_spinner=False)
def fetch_accounts():
    """Non-house (client) accounts."""
    return api_get("/accounts") or []


@st.cache_data(ttl=5, show_spinner=False)
def fetch_all_accounts():
    """All accounts, with the house / market-maker account (id 1) first."""
    accounts = api_get("/accounts") or []
    house = api_get("/accounts/1", quiet=True)
    if house and house.get("is_house"):
        accounts = [house] + accounts
    return accounts


@st.cache_data(ttl=5, show_spinner=False)
def fetch_price_bars(instrument_id: int, days: int = 252) -> pd.DataFrame:
    bars = api_get(f"/instruments/{instrument_id}/price-bars", params={"days": days}, quiet=True) or []
    df = pd.DataFrame(bars)
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@st.cache_data(ttl=5, show_spinner=False)
def fetch_order_book_depth(instrument_id: int):
    return api_get(f"/analytics/order-book-depth/{instrument_id}", quiet=True) or []


@st.cache_data(ttl=5, show_spinner=False)
def fetch_vwap(instrument_id: int):
    return api_get(f"/analytics/vwap/{instrument_id}", quiet=True) or []


@st.cache_data(ttl=5, show_spinner=False)
def fetch_portfolio(account_id: int):
    return api_get(f"/analytics/portfolio/{account_id}") or {}


@st.cache_data(ttl=5, show_spinner=False)
def fetch_realized_pnl(account_id: int):
    return api_get(f"/analytics/realized-pnl/{account_id}") or []


@st.cache_data(ttl=5, show_spinner=False)
def fetch_orders(account_id: int, status: str = "ALL"):
    params = {"account_id": account_id}
    if status != "ALL":
        params["status"] = status
    return api_get("/orders", params=params) or []


@st.cache_data(ttl=5, show_spinner=False)
def fetch_rolling_returns(instrument_id: int):
    return api_get(f"/analytics/rolling-returns/{instrument_id}") or []


@st.cache_data(ttl=5, show_spinner=False)
def fetch_holdings_vs_cash():
    return api_get("/analytics/holdings-vs-cash") or []


@st.cache_data(ttl=5, show_spinner=False)
def fetch_bond_ytm(instrument_id: int):
    return api_get(f"/analytics/bond-ytm/{instrument_id}")


@st.cache_data(ttl=5, show_spinner=False)
def fetch_ledger(account_id: int, limit: int = 50):
    return api_get(f"/accounts/{account_id}/ledger", params={"limit": limit}) or []


@st.cache_data(ttl=5, show_spinner=False)
def fetch_market_snapshot() -> pd.DataFrame:
    """
    One row per instrument: last price, day change, 52-week range and a
    30-session close history (for sparklines). Built from /price-bars.
    """
    rows = []
    for inst in fetch_instruments():
        bars = fetch_price_bars(inst["instrument_id"], 252)
        row = {
            "instrument_id": inst["instrument_id"],
            "symbol": inst["symbol"],
            "name": inst["name"],
            "instrument_type": inst["instrument_type"],
            "sector": inst.get("sector"),
            "status": inst.get("status", "ACTIVE"),
            "multiplier": float(inst.get("multiplier") or 1),
            "last": None,
            "prev_close": None,
            "change": None,
            "change_pct": None,
            "volume": None,
            "high_52w": None,
            "low_52w": None,
            "trend": [],
        }
        if not bars.empty:
            last = bars.iloc[-1]
            prev = bars.iloc[-2] if len(bars) > 1 else last
            row.update(
                last=float(last["close"]),
                prev_close=float(prev["close"]),
                change=float(last["close"] - prev["close"]),
                change_pct=float((last["close"] - prev["close"]) / prev["close"] * 100) if prev["close"] else 0.0,
                volume=float(last["volume"]) if pd.notna(last["volume"]) else None,
                high_52w=float(bars["high"].max()),
                low_52w=float(bars["low"].min()),
                trend=bars["close"].tail(30).round(2).tolist(),
            )
        rows.append(row)
    return pd.DataFrame(rows)


def clear_all_caches():
    """Invalidate everything after a mutating call (order, cancel, deposit)."""
    st.cache_data.clear()
