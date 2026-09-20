import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
from fyers_apiv3 import fyersModel

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

IST = ZoneInfo("Asia/Kolkata")
CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "M2DACFCYUO-100").strip()
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
NIFTY = "NSE:NIFTY50-INDEX"
VIX = "NSE:INDIAVIX-INDEX"

# Keep the first version deliberately bounded to liquid, widely traded NSE names.
# Add/remove symbols from this list without changing the signal engine.
WATCHLIST = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK",
    "INDUSINDBK", "BANKBARODA", "TCS", "INFY", "HCLTECH", "WIPRO",
    "TECHM", "LTIM", "BHARTIARTL", "TATASTEEL", "JSWSTEEL", "HINDALCO",
    "ADANIENT", "ADANIPORTS", "LT", "M&M", "MARUTI", "TATAMOTORS",
    "EICHERMOT", "SUNPHARMA", "DRREDDY", "CIPLA", "APOLLOHOSP",
    "ITC", "HINDUNILVR", "ASIANPAINT", "TITAN", "TRENT", "BEL",
    "POWERGRID", "NTPC", "ONGC", "COALINDIA", "ULTRACEMCO",
    "NESTLEIND", "BAJFINANCE", "BAJAJFINSV", "SHRIRAMFIN", "HAL",
    "ETERNAL", "ZOMATO", "IRFC", "RVNL", "INDIGO",
]

st.set_page_config(page_title="NSE Signal Lab", page_icon="⚡", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1500px; }
[data-testid="stMetricValue"] { font-size: 1.55rem; }
.signal-card { border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: 14px; margin-bottom: 8px; }
.small { font-size: .82rem; opacity: .72; }
</style>
""", unsafe_allow_html=True)


def fyers_client():
    if not ACCESS_TOKEN:
        st.error("FYERS_ACCESS_TOKEN is not configured. Add it as a Streamlit secret/environment variable.")
        st.stop()
    return fyersModel.FyersModel(client_id=CLIENT_ID, token=ACCESS_TOKEN, is_async=False, log_path="")


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df, period=14):
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def fetch_candles(client, symbol, days=12, resolution="15"):
    end = datetime.now(IST).date()
    start = end - timedelta(days=days)
    response = client.history({
        "symbol": symbol,
        "resolution": resolution,
        "date_format": "1",
        "range_from": start.isoformat(),
        "range_to": end.isoformat(),
        "cont_flag": "1",
    })
    if response.get("s") != "ok":
        raise RuntimeError(response.get("message", "FYERS history request failed"))
    rows = response.get("candles", [])
    if not rows:
        raise RuntimeError("No candle data")
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["dt"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(IST)
    return df.sort_values("dt").reset_index(drop=True)


def quote(client, symbol):
    response = client.quotes({"symbols": symbol})
    if response.get("s") != "ok" or not response.get("d"):
        raise RuntimeError("Quote unavailable")
    return float(response["d"][0]["v"]["lp"])


def enrich(df):
    x = df.copy()
    x["ema20"] = x["close"].ewm(span=20, adjust=False).mean()
    x["ema50"] = x["close"].ewm(span=50, adjust=False).mean()
    x["rsi"] = rsi(x["close"])
    x["atr"] = atr(x)
    x["vol20"] = x["volume"].rolling(20).mean()
    x["high20"] = x["high"].rolling(20).max().shift(1)
    x["low20"] = x["low"].rolling(20).min().shift(1)
    return x


def make_signal(symbol, df):
    x = enrich(df).dropna().copy()
    if len(x) < 60:
        raise RuntimeError("Not enough candles")
    last = x.iloc[-1]
    prev = x.iloc[-2]
    price = float(last.close)
    a = max(float(last.atr), price * 0.002)
    score = 0
    reasons = []

    if last.close > last.ema20:
        score += 1
        reasons.append("price above EMA20")
    else:
        score -= 1
        reasons.append("price below EMA20")
    if last.ema20 > last.ema50:
        score += 1
        reasons.append("EMA20 above EMA50")
    else:
        score -= 1
        reasons.append("EMA20 below EMA50")
    if last.rsi >= 55:
        score += 1
        reasons.append(f"RSI {last.rsi:.0f} supports momentum")
    elif last.rsi <= 45:
        score -= 1
        reasons.append(f"RSI {last.rsi:.0f} shows weak momentum")
    else:
        reasons.append(f"RSI {last.rsi:.0f} is neutral")
    if last.volume > last.vol20 * 1.25:
        score += 1 if last.close >= prev.close else -1
        reasons.append(f"relative volume {last.volume / last.vol20:.1f}x")
    if last.close > last.high20:
        score += 2
        reasons.append("20-bar breakout")
    elif last.close < last.low20:
        score -= 2
        reasons.append("20-bar breakdown")

    if score >= 3:
        signal = "BUY"
        entry = price
        sl = price - 1.2 * a
        t1 = price + 1.5 * a
        t2 = price + 2.5 * a
    elif score <= -3:
        signal = "SELL"
        entry = price
        sl = price + 1.2 * a
        t1 = price - 1.5 * a
        t2 = price - 2.5 * a
    else:
        signal = "WATCH"
        entry = price
        sl = np.nan
        t1 = np.nan
        t2 = np.nan

    # This is a confluence score, not a probability of profit.
    confidence = min(95, 50 + abs(score) * 8)
    return {
        "Symbol": symbol,
        "Signal": signal,
        "Price": round(price, 2),
        "Entry": round(entry, 2),
        "SL": round(sl, 2) if pd.notna(sl) else np.nan,
        "T1": round(t1, 2) if pd.notna(t1) else np.nan,
        "T2": round(t2, 2) if pd.notna(t2) else np.nan,
        "Score": score,
        "Confidence": f"{confidence}%",
        "RSI": round(float(last.rsi), 1),
        "RVOL": round(float(last.volume / last.vol20), 2),
        "Reasons": "; ".join(reasons),
        "Updated": last.dt.strftime("%H:%M:%S"),
    }


@st.cache_data(ttl=60, show_spinner=False)
def scan_market(symbols):
    client = fyers_client()
    results = []
    errors = []
    for name in symbols:
        try:
            results.append(make_signal(name, fetch_candles(client, f"NSE:{name}-EQ")))
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return pd.DataFrame(results), errors


@st.cache_data(ttl=30, show_spinner=False)
def market_snapshot():
    client = fyers_client()
    nifty = quote(client, NIFTY)
    vix = quote(client, VIX)
    nf = enrich(fetch_candles(client, NIFTY, days=12))
    last = nf.iloc[-1]
    regime = "BULLISH" if last.close > last.ema20 > last.ema50 else "BEARISH" if last.close < last.ema20 < last.ema50 else "MIXED"
    return {
        "nifty": nifty,
        "vix": vix,
        "regime": regime,
        "ema20": float(last.ema20),
        "ema50": float(last.ema50),
        "updated": last.dt.strftime("%d %b %H:%M:%S IST"),
    }


# ----------------------------- UI -----------------------------
now = datetime.now(IST)
st.title("⚡ NSE SIGNAL LAB")
st.caption("FYERS live market data • 15-minute signal engine • paper-trading first")

if st_autorefresh:
    st_autorefresh(interval=60_000, key="market_refresh")

with st.sidebar:
    st.header("Controls")
    universe_size = st.slider("Stocks to scan", 10, len(WATCHLIST), 50, 5)
    min_score = st.slider("Minimum absolute score", 1, 5, 3)
    signal_filter = st.multiselect("Signals", ["BUY", "SELL", "WATCH"], default=["BUY", "SELL", "WATCH"])
    st.divider()
    st.write("**Mode:** PAPER SIGNALS")
    st.write("No live orders are placed by this dashboard.")
    st.write(f"Auto-refresh: 60s")

try:
    snap = market_snapshot()
except Exception as exc:
    st.error(f"Market data error: {exc}")
    st.stop()

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("NIFTY 50", f"{snap['nifty']:,.2f}")
m2.metric("India VIX", f"{snap['vix']:.2f}")
m3.metric("REGIME", snap["regime"])
m4.metric("EMA20", f"{snap['ema20']:,.0f}")
m5.metric("EMA50", f"{snap['ema50']:,.0f}")
st.caption(f"Last market candle: {snap['updated']}")

with st.spinner("Scanning NSE..."):
    data, errors = scan_market(tuple(WATCHLIST[:universe_size]))

if data.empty:
    st.warning("No signals returned. Check the FYERS token and market-data permissions.")
    st.stop()

filtered = data[(data["Score"].abs() >= min_score) & data["Signal"].isin(signal_filter)].copy()
filtered = filtered.sort_values(["Signal", "Score"], ascending=[True, False])

buy = data[data.Signal == "BUY"].sort_values("Score", ascending=False)
sell = data[data.Signal == "SELL"].sort_values("Score")
watch = data[data.Signal == "WATCH"].copy()

st.subheader("Signal Board")
left, right = st.columns([1, 1])
with left:
    st.markdown("### 🟢 BUY setups")
    if buy.empty:
        st.info("No BUY setup currently meets the threshold.")
    else:
        for _, r in buy.head(5).iterrows():
            st.markdown(f"**{r.Symbol}** · Entry ₹{r.Entry:,.2f} · SL ₹{r.SL:,.2f} · T1 ₹{r.T1:,.2f} · T2 ₹{r.T2:,.2f} · {r.Confidence}")
            st.caption(r.Reasons)
with right:
    st.markdown("### 🔴 SELL setups")
    if sell.empty:
        st.info("No SELL setup currently meets the threshold.")
    else:
        for _, r in sell.head(5).iterrows():
            st.markdown(f"**{r.Symbol}** · Entry ₹{r.Entry:,.2f} · SL ₹{r.SL:,.2f} · T1 ₹{r.T1:,.2f} · T2 ₹{r.T2:,.2f} · {r.Confidence}")
            st.caption(r.Reasons)

st.subheader("Scanner")
show_cols = ["Symbol", "Signal", "Price", "Entry", "SL", "T1", "T2", "Score", "Confidence", "RSI", "RVOL", "Updated"]
st.dataframe(filtered[show_cols], use_container_width=True, hide_index=True)

with st.expander("How the signal is calculated"):
    st.markdown("""
**15-minute confluence engine**

- Trend: price vs EMA20 and EMA20 vs EMA50
- Momentum: RSI(14)
- Participation: relative volume vs 20-bar average
- Structure: 20-bar breakout/breakdown
- Risk: ATR(14)-based stop and target distances

**BUY/SELL requires a score of ±3 or stronger.** WATCH means the setup does not have enough confluence. The displayed percentage is a **confluence score**, not a probability of profit.

The first version is intentionally deterministic so every call can be audited and paper-traded. Historical win-rate/backtesting will be added before any live-order automation.
""")

if errors:
    with st.expander(f"Data warnings ({len(errors)})"):
        st.code("\n".join(errors[:30]))

st.divider()
st.caption(f"NSE Signal Lab • {now.strftime('%d %b %Y %H:%M:%S IST')} • Paper signals only")
