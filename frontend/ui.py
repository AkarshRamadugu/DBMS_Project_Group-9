"""
Visual layer for the Streamlit frontend: global CSS, Plotly theme,
number formatting and small HTML components (app bar, ticker tape,
KPI cards, market-depth ladder, badges).
"""

import html
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
BG = "#0b0e14"
PANEL = "#111722"
PANEL_2 = "#161d2b"
BORDER = "#1f2838"
TEXT = "#e6e9ef"
MUTED = "#8b95a9"
FAINT = "#5b6478"
ACCENT = "#3b82f6"
UP = "#16c784"
DOWN = "#ea3943"
AMBER = "#f5a524"
TYPE_COLORS = {"STOCK": "#3b82f6", "BOND": "#a78bfa", "OPTION": "#f5a524"}

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------
_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {{
  --bg:{BG}; --panel:{PANEL}; --panel2:{PANEL_2}; --border:{BORDER};
  --text:{TEXT}; --muted:{MUTED}; --faint:{FAINT};
  --accent:{ACCENT}; --up:{UP}; --down:{DOWN}; --amber:{AMBER};
  --mono:'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
}}
html, body, [class*="css"], .stApp, .stMarkdown, button, input, select, textarea {{
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
}}
.stApp {{ background: var(--bg); }}

/* ---- Streamlit chrome ------------------------------------------------ */
[data-testid="stDecoration"], [data-testid="stAppDeployButton"],
[data-testid="stMainMenu"], footer {{ display: none !important; }}
header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
.block-container {{ padding: 0.9rem 1.6rem 3rem 1.6rem !important; max-width: 100% !important; }}
[data-testid="stVerticalBlock"] {{ gap: 0.75rem; }}

/* ---- Sidebar ---------------------------------------------------------- */
section[data-testid="stSidebar"] {{ background: #0d121b; border-right: 1px solid var(--border); }}
section[data-testid="stSidebar"] .block-container {{ padding-top: 0.5rem !important; }}
[data-testid="stSidebarNav"] {{ padding-top: 0.25rem; }}
[data-testid="stSidebarNavLink"] {{ border-radius: 8px; margin: 1px 8px; padding: 0.45rem 0.75rem; }}
[data-testid="stSidebarNavLink"] span {{ color: var(--muted); font-weight: 500; font-size: 0.92rem; }}
[data-testid="stSidebarNavLink"]:hover {{ background: var(--panel2); }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{ background: rgba(59,130,246,0.14); }}
[data-testid="stSidebarNavLink"][aria-current="page"] span {{ color: #fff; }}
[data-testid="stSidebarNavSeparator"] {{ border-color: var(--border); }}

/* ---- Typography ------------------------------------------------------- */
h1, h2, h3, h4 {{ letter-spacing: -0.01em; color: var(--text); }}
.mono, .num {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.up {{ color: var(--up) !important; }}
.down {{ color: var(--down) !important; }}
.muted {{ color: var(--muted); }}
.section-title {{
  font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); margin: 0.2rem 0 0.4rem 0; display:flex; align-items:center; gap:.5rem;
}}
.section-title .hint {{ text-transform:none; letter-spacing:0; font-weight:400; color:var(--faint); }}

/* ---- Bordered containers act as panels -------------------------------- */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:first-child .pm) {{
  border: 1px solid var(--border) !important; background: var(--panel); border-radius: 12px;
}}
[data-testid="stElementContainer"]:has(.pm) {{ display: none; }}

/* ---- App bar ---------------------------------------------------------- */
.appbar {{
  display:flex; align-items:center; justify-content:space-between; gap:1rem;
  padding: 0.55rem 0.9rem; background: var(--panel); border:1px solid var(--border);
  border-radius: 12px; margin-bottom: 0.15rem;
}}
.brand {{ display:flex; align-items:center; gap:0.7rem; }}
.brand-mark {{ width:34px; height:34px; border-radius:9px; display:grid; place-items:center;
  background: linear-gradient(135deg,#2563eb 0%,#16c784 100%); }}
.brand-name {{ font-weight:700; font-size:1.05rem; color:#fff; line-height:1.1; }}
.brand-sub {{ font-size:0.72rem; color:var(--muted); letter-spacing:0.04em; }}
.appbar-right {{ display:flex; align-items:center; gap:0.6rem; flex-wrap:wrap; justify-content:flex-end; }}
.chip {{ display:inline-flex; align-items:center; gap:0.4rem; padding:0.28rem 0.65rem; border-radius:999px;
  background: var(--panel2); border:1px solid var(--border); font-size:0.78rem; color:var(--muted); white-space:nowrap; }}
.chip b {{ color: var(--text); font-weight:600; }}
.dot {{ width:7px; height:7px; border-radius:50%; display:inline-block; }}
.dot.live {{ background: var(--up); box-shadow: 0 0 0 0 rgba(22,199,132,.6); animation: pulse 1.8s infinite; }}
.dot.off {{ background: var(--down); }}
@keyframes pulse {{ 0% {{ box-shadow:0 0 0 0 rgba(22,199,132,.55); }} 70% {{ box-shadow:0 0 0 7px rgba(22,199,132,0); }} 100% {{ box-shadow:0 0 0 0 rgba(22,199,132,0); }} }}

/* ---- Ticker tape ------------------------------------------------------ */
.ticker {{ overflow:hidden; white-space:nowrap; border:1px solid var(--border); border-radius:10px;
  background: #0d121b; padding: 0.42rem 0; position:relative; margin-bottom: 0.35rem; }}
.ticker::before, .ticker::after {{ content:""; position:absolute; top:0; bottom:0; width:48px; z-index:2; }}
.ticker::before {{ left:0; background: linear-gradient(90deg,#0d121b,transparent); }}
.ticker::after {{ right:0; background: linear-gradient(270deg,#0d121b,transparent); }}
.ticker-track {{ display:inline-block; animation: tick 60s linear infinite; }}
.ticker:hover .ticker-track {{ animation-play-state: paused; }}
.tk {{ display:inline-flex; gap:0.45rem; align-items:baseline; margin: 0 1.4rem; font-size:0.82rem; }}
.tk .s {{ font-weight:600; color:var(--text); }}
.tk .p {{ font-family:var(--mono); color:var(--text); }}
.tk .c {{ font-family:var(--mono); font-size:0.78rem; }}
@keyframes tick {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}

/* ---- Page header ------------------------------------------------------ */
.page-head {{ display:flex; align-items:flex-end; justify-content:space-between; margin: 0.2rem 0 0.5rem 0; }}
.page-head h2 {{ margin:0; padding:0; font-size:1.45rem; font-weight:700; }}
.page-head .sub {{ color:var(--muted); font-size:0.85rem; margin-top:0.15rem; }}

/* ---- Quote header ----------------------------------------------------- */
.quote {{ display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:1rem; }}
.quote .sym {{ font-size:1.5rem; font-weight:700; color:#fff; line-height:1.1; }}
.quote .nm {{ color:var(--muted); font-size:0.88rem; margin-top:0.2rem; }}
.quote .px {{ font-family:var(--mono); font-size:2rem; font-weight:600; color:#fff; line-height:1; text-align:right; }}
.quote .chg {{ font-family:var(--mono); font-size:0.95rem; text-align:right; margin-top:0.3rem; }}
.badge {{ display:inline-block; padding:0.1rem 0.5rem; border-radius:6px; font-size:0.68rem; font-weight:600;
  letter-spacing:0.05em; text-transform:uppercase; border:1px solid; margin-left:0.35rem; vertical-align:middle; }}
.stats {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap:0; margin-top:0.9rem;
  border-top:1px solid var(--border); }}
.stat {{ padding:0.6rem 0.2rem 0.1rem 0; }}
.stat .k {{ font-size:0.7rem; color:var(--faint); text-transform:uppercase; letter-spacing:0.06em; }}
.stat .v {{ font-family:var(--mono); font-size:0.95rem; color:var(--text); margin-top:0.15rem; }}

/* ---- KPI cards -------------------------------------------------------- */
.kpi {{ background: var(--panel); border:1px solid var(--border); border-radius:12px; padding:0.85rem 1rem; height:100%; }}
.kpi .k {{ font-size:0.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.07em; font-weight:600; }}
.kpi .v {{ font-family:var(--mono); font-size:clamp(1rem, 1.3vw, 1.45rem); font-weight:600; color:#fff; margin-top:0.3rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.kpi .d {{ font-size:0.8rem; margin-top:0.2rem; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}

/* ---- Market depth ladder --------------------------------------------- */
.dl-row {{ display:grid; grid-template-columns: 1.3fr 1fr 0.8fr 1fr; align-items:center;
  font-family:var(--mono); font-size:0.82rem; padding:0.28rem 0.45rem; border-bottom:1px solid rgba(31,40,56,.45); }}
.dl-row > span {{ text-align:right; }}
.dl-row > span:first-child {{ text-align:left; }}
.dl-head {{ font-family:'Inter',sans-serif; font-size:0.66rem; font-weight:600; color:var(--faint);
  text-transform:uppercase; letter-spacing:0.06em; border-bottom:1px solid var(--border); }}
.dl-tot {{ color:var(--muted); font-weight:600; border-top:1px solid var(--border); border-bottom:none; }}
.spread {{ display:flex; justify-content:space-between; font-size:0.78rem; color:var(--muted);
  padding:0.4rem 0.55rem; background:var(--panel2); border-radius:6px; margin:0.3rem 0; }}
.imbalance {{ margin:0.7rem 0 0.35rem 0; }}
.imbalance .bar {{ height:5px; border-radius:3px; background:var(--down); overflow:hidden; }}
.imbalance .bar > div {{ height:100%; background:var(--up); }}
.imbalance .lbl {{ display:flex; justify-content:space-between; font-family:var(--mono); font-size:0.72rem; margin-top:0.3rem; }}
.spread b {{ font-family:var(--mono); color:var(--text); font-weight:500; }}
.empty {{ color:var(--faint); text-align:center; padding:1.2rem 0; font-size:0.85rem; }}

/* ---- Reset Streamlit's markdown table chrome -------------------------- */
.stMarkdown table.tbl, .stMarkdown table.tbl tr, .stMarkdown table.tbl th, .stMarkdown table.tbl td {{
  border-left: none !important; border-right: none !important; border-top: none !important; background: transparent;
}}
.stMarkdown table.tbl {{ border: none !important; width: 100% !important; margin: 0 !important; }}
.stMarkdown table.tbl tr:nth-child(even) {{ background: transparent; }}

/* ---- Generic HTML table ---------------------------------------------- */
.tbl {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
.tbl th {{ font-size:0.68rem; font-weight:600; color:var(--faint) !important; text-transform:uppercase; letter-spacing:0.06em;
  padding:0.45rem 0.5rem !important; border-bottom:1px solid var(--border) !important; text-align:right; white-space:nowrap; }}
.tbl td {{ padding:0.5rem 0.5rem !important; border-bottom:1px solid rgba(31,40,56,.55) !important; text-align:right;
  font-family:var(--mono); font-size:0.82rem; white-space:nowrap; vertical-align:middle; }}
.tbl th:first-child, .tbl td:first-child {{ text-align:left; }}
.tbl td.txt {{ font-family:inherit; white-space:normal; }}
.tbl tr:hover td {{ background: rgba(59,130,246,0.05); }}
.pill {{ display:inline-block; padding:0.12rem 0.5rem; border-radius:999px; font-size:0.7rem; font-weight:600;
  font-family:'Inter',sans-serif; letter-spacing:0.03em; }}
.pill.buy, .pill.filled {{ background:rgba(22,199,132,.13); color:var(--up); }}
.pill.sell, .pill.cancelled {{ background:rgba(234,57,67,.13); color:var(--down); }}
.pill.open {{ background:rgba(59,130,246,.15); color:#7fb0ff; }}
.pill.partial {{ background:rgba(245,165,36,.15); color:var(--amber); }}
.pill.neutral {{ background:var(--panel2); color:var(--muted); }}

/* ---- Widgets ---------------------------------------------------------- */
[data-testid="stMetric"] {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:0.8rem 1rem; }}
[data-testid="stMetricValue"] {{ font-family:var(--mono); font-size:1.35rem; }}
.stTabs [data-baseweb="tab-list"] {{ gap:0.25rem; border-bottom:1px solid var(--border); }}
.stTabs [data-baseweb="tab"] {{ padding:0.5rem 0.9rem; color:var(--muted); }}
.stTabs [aria-selected="true"] {{ color:#fff; }}
div[data-baseweb="select"] > div, .stNumberInput input, .stTextInput input {{ background: var(--panel2) !important; border-color: var(--border) !important; }}
.stNumberInput input {{ font-family: var(--mono); }}
.stButton button, .stFormSubmitButton button {{ border-radius:8px; font-weight:600; }}
[data-testid="stDataFrame"] {{ border:1px solid var(--border); border-radius:10px; overflow:hidden; }}
[data-testid="stExpander"] details {{ border-color: var(--border); background: var(--panel); border-radius:12px; }}

/* Buy / sell coloured buttons (Streamlit exposes .st-key-<key> wrappers) */
[class*="st-key-buy"] button {{ background:var(--up) !important; border-color:var(--up) !important; color:#04140d !important; }}
[class*="st-key-sell"] button {{ background:var(--down) !important; border-color:var(--down) !important; color:#fff !important; }}
[class*="st-key-buy"] button:hover, [class*="st-key-sell"] button:hover {{ filter:brightness(1.1); }}
[class*="st-key-side_off"] button {{ background:var(--panel2) !important; border-color:var(--border) !important; color:var(--muted) !important; }}
</style>
"""

_LOGO = (
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round"><polyline points="3 17 9 11 13 15 21 7"/>'
    '<polyline points="15 7 21 7 21 13"/></svg>'
)


def inject_css():
    st.markdown(_CSS, unsafe_allow_html=True)


@contextmanager
def panel():
    """Bordered card. The hidden .pm marker lets the CSS give it the panel background."""
    with st.container(border=True) as c:
        st.markdown('<span class="pm"></span>', unsafe_allow_html=True)
        yield c


def html_block(markup: str):
    """Render raw HTML. Lines are stripped so Markdown never sees an indented code block."""
    st.markdown("".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Plotly theme
# ---------------------------------------------------------------------------
def register_plotly_theme():
    tpl = go.layout.Template()
    tpl.layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color=MUTED, size=12),
        colorway=[ACCENT, UP, AMBER, "#a78bfa", DOWN, "#22d3ee", "#f472b6"],
        xaxis=dict(gridcolor="rgba(31,40,56,0.6)", linecolor=BORDER, zerolinecolor=BORDER, showspikes=True,
                   spikecolor=FAINT, spikethickness=1, spikedash="dot", spikemode="across"),
        yaxis=dict(gridcolor="rgba(31,40,56,0.6)", linecolor=BORDER, zerolinecolor=BORDER, side="right",
                   showspikes=True, spikecolor=FAINT, spikethickness=1, spikedash="dot"),
        hoverlabel=dict(bgcolor=PANEL_2, bordercolor=BORDER, font=dict(family="JetBrains Mono, monospace", color=TEXT)),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=8, r=8, t=28, b=8),
        hovermode="x unified",
    )
    pio.templates["ptx"] = tpl
    pio.templates.default = "ptx"


PLOTLY_CONFIG = {"displayModeBar": False, "scrollZoom": False}


def chart(fig):
    """Render a Plotly figure with the PTX template (Streamlit's own theme would override it)."""
    if "ptx" not in pio.templates:
        register_plotly_theme()
    fig.update_layout(template=pio.templates["ptx"], paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Inter, sans-serif", color=MUTED, size=12))
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, theme=None)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _indian_group(int_part: str) -> str:
    if len(int_part) <= 3:
        return int_part
    head, tail = int_part[:-3], int_part[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def fmt_num(value, decimals: int = 2, sign: bool = False) -> str:
    """Indian digit grouping (12,34,567.89)."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if v != v:  # NaN
        return "—"
    neg = v < 0
    s = f"{abs(v):.{decimals}f}"
    int_part, _, frac = s.partition(".")
    out = _indian_group(int_part) + (f".{frac}" if frac else "")
    if neg:
        return "−" + out
    return ("+" + out) if sign and v > 0 else out


def fmt_inr(value, decimals: int = 2, sign: bool = False) -> str:
    s = fmt_num(value, decimals, sign)
    if s == "—":
        return s
    if s[0] in "+−":
        return f"{s[0]}₹{s[1:]}"
    return f"₹{s}"


def fmt_compact(value) -> str:
    """₹ in lakh / crore for big headline numbers."""
    if value is None:
        return "—"
    v = float(value)
    a = abs(v)
    sgn = "−" if v < 0 else ""
    if a >= 1e7:
        return f"{sgn}₹{a / 1e7:,.2f} Cr"
    if a >= 1e5:
        return f"{sgn}₹{a / 1e5:,.2f} L"
    return fmt_inr(v)


def fmt_pct(value, sign: bool = True, decimals: int = 2) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    s = f"{abs(v):.{decimals}f}%"
    if v < 0:
        return "−" + s
    return ("+" + s) if sign and v > 0 else s


def tone(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "muted"
    return "up" if v > 0 else "down" if v < 0 else "muted"


def arrow(value) -> str:
    t = tone(value)
    return "▲" if t == "up" else "▼" if t == "down" else "•"


def esc(x) -> str:
    return html.escape(str(x)) if x is not None else "—"


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
def type_badge(instrument_type: str) -> str:
    c = TYPE_COLORS.get(str(instrument_type).upper(), MUTED)
    return f'<span class="badge" style="color:{c};border-color:{c}55;background:{c}14">{esc(instrument_type)}</span>'


def status_pill(status: str) -> str:
    s = str(status).upper()
    return f'<span class="pill {s.lower()}">{esc(s)}</span>'


def side_pill(side: str) -> str:
    s = str(side).upper()
    return f'<span class="pill {s.lower()}">{esc(s)}</span>'


def app_bar(api_ok: bool, account_label: str | None):
    now = datetime.now(IST)
    status = (
        '<span class="chip"><span class="dot live"></span><b>Live</b> Exchange online</span>'
        if api_ok
        else '<span class="chip"><span class="dot off"></span><b>Offline</b> API unreachable</span>'
    )
    acct = f'<span class="chip">Account <b>{esc(account_label)}</b></span>' if account_label else ""
    html_block(f"""
    <div class="appbar">
      <div class="brand">
        <div class="brand-mark">{_LOGO}</div>
        <div><div class="brand-name">PTX Terminal</div>
        <div class="brand-sub">PAPER TRADING EXCHANGE</div></div>
      </div>
      <div class="appbar-right">
        {acct}
        {status}
        <span class="chip">{now:%a, %d %b %Y} · <b>{now:%H:%M}</b> IST</span>
      </div>
    </div>
    """)


def ticker_tape(snapshot):
    if snapshot is None or snapshot.empty:
        return
    items = []
    for _, r in snapshot.iterrows():
        if r["last"] is None or r["last"] != r["last"]:
            continue
        t = tone(r["change"])
        items.append(
            f'<span class="tk"><span class="s">{esc(r["symbol"])}</span>'
            f'<span class="p">{fmt_num(r["last"])}</span>'
            f'<span class="c {t}">{arrow(r["change"])} {fmt_num(r["change"], 2, True)} ({fmt_pct(r["change_pct"])})</span></span>'
        )
    if not items:
        return
    track = "".join(items)
    html_block(f'<div class="ticker"><div class="ticker-track">{track}{track}</div></div>')


def page_header(title: str, subtitle: str = ""):
    sub = f'<div class="sub">{esc(subtitle)}</div>' if subtitle else ""
    html_block(f'<div class="page-head"><div><h2>{esc(title)}</h2>{sub}</div></div>')


def section_title(title: str, hint: str = ""):
    h = f'<span class="hint">· {esc(hint)}</span>' if hint else ""
    html_block(f'<div class="section-title">{esc(title)}{h}</div>')


def kpi(label: str, value: str, delta: str = "", delta_tone: str = "muted"):
    d = f'<div class="d {delta_tone}">{delta}</div>' if delta else '<div class="d">&nbsp;</div>'
    html_block(f'<div class="kpi"><div class="k">{esc(label)}</div><div class="v">{value}</div>{d}</div>')


def kpi_row(items):
    """items: list of (label, value, delta, tone)."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        with col:
            kpi(*item)


def quote_header(row: dict, stats: list[tuple[str, str]]):
    t = tone(row.get("change"))
    sector = f'<span class="muted"> · {esc(row.get("sector"))}</span>' if row.get("sector") else ""
    status = str(row.get("status", "ACTIVE")).upper()
    status_b = "" if status == "ACTIVE" else f'<span class="badge" style="color:{DOWN};border-color:{DOWN}55">{esc(status)}</span>'
    stats_html = "".join(f'<div class="stat"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>' for k, v in stats)
    html_block(f"""
    <div class="quote">
      <div>
        <div class="sym">{esc(row.get("symbol"))}{type_badge(row.get("instrument_type"))}{status_b}</div>
        <div class="nm">{esc(row.get("name"))}{sector}</div>
      </div>
      <div>
        <div class="px">{fmt_inr(row.get("last"))}</div>
        <div class="chg {t}">{arrow(row.get("change"))} {fmt_num(row.get("change"), 2, True)} ({fmt_pct(row.get("change_pct"))})</div>
      </div>
    </div>
    <div class="stats">{stats_html}</div>
    """)


def depth_ladder(depth_rows, levels: int = 8):
    """
    Vertical depth-of-market ladder: offers on top (best ask nearest the
    spread), bids below. Bars are proportional to resting quantity; the
    Total column is the running `cumulative_qty` from the SQL window query.
    """
    bids = sorted([r for r in depth_rows if r.get("side") == "BUY"], key=lambda r: float(r["price"]), reverse=True)[:levels]
    asks = sorted([r for r in depth_rows if r.get("side") == "SELL"], key=lambda r: float(r["price"]))[:levels]
    qty = lambda r: float(r.get("level_qty") or r.get("total_qty") or 0)  # noqa: E731
    max_q = max([qty(r) for r in bids + asks] or [1]) or 1

    def row(r, is_bid, cum):
        colour = "22,199,132" if is_bid else "234,57,67"
        w = qty(r) / max_q * 100
        bar = f"background:linear-gradient(270deg, rgba({colour},0.16) {w:.1f}%, transparent {w:.1f}%);"
        return (
            f'<div class="dl-row" style="{bar}"><span class="{"up" if is_bid else "down"}">{fmt_num(r["price"])}</span>'
            f'<span>{fmt_num(qty(r), 0)}</span><span class="muted">{int(r.get("order_count") or 0)}</span>'
            f'<span class="muted">{fmt_num(cum, 0)}</span></div>'
        )

    head = '<div class="dl-row dl-head"><span>Price</span><span>Qty</span><span>Orders</span><span>Total</span></div>'
    parts = [head]
    if asks:
        cums, c = [], 0.0
        for r in asks:
            c = float(r.get("cumulative_qty") or (c + qty(r)))
            cums.append(c)
        parts += [row(r, False, c) for r, c in reversed(list(zip(asks, cums)))]
    else:
        parts.append('<div class="empty">No offers</div>')

    best_bid = float(bids[0]["price"]) if bids else None
    best_ask = float(asks[0]["price"]) if asks else None
    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        mid = (best_ask + best_bid) / 2
        parts.append(
            f'<div class="spread"><span>Spread <b>{fmt_num(spread)}</b> '
            f'<span class="muted">({fmt_pct(spread / mid * 100, sign=False, decimals=3)})</span></span>'
            f'<span>Mid <b>{fmt_num(mid)}</b></span></div>'
        )
    else:
        parts.append('<div class="spread"><span>One-sided book</span><span>Spread <b>—</b></span></div>')

    if bids:
        c = 0.0
        for r in bids:
            c = float(r.get("cumulative_qty") or (c + qty(r)))
            parts.append(row(r, True, c))
    else:
        parts.append('<div class="empty">No bids</div>')

    tb = sum(qty(r) for r in bids)
    ta = sum(qty(r) for r in asks)
    share = tb / (tb + ta) * 100 if (tb + ta) else 50
    parts.append(
        f'<div class="imbalance"><div class="bar"><div style="width:{share:.1f}%"></div></div>'
        f'<div class="lbl"><span class="up">Bids {fmt_num(tb, 0)} · {share:.0f}%</span>'
        f'<span class="down">{100 - share:.0f}% · {fmt_num(ta, 0)} Offers</span></div></div>'
    )
    html_block("".join(parts))


def html_table(headers, rows, align_left=1):
    """Simple themed table. rows are lists of pre-formatted HTML strings."""
    th = "".join(f"<th>{h}</th>" for h in headers)
    trs = []
    for r in rows:
        tds = "".join(
            f'<td class="txt">{c}</td>' if i < align_left else f"<td>{c}</td>" for i, c in enumerate(r)
        )
        trs.append(f"<tr>{tds}</tr>")
    html_block(f'<div style="overflow-x:auto"><table class="tbl"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>')


def empty_state(message: str, icon: str = "inbox"):
    html_block(f'<div class="empty">{esc(message)}</div>')
