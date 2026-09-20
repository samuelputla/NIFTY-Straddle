# NSE Signal Lab

A paper-signal dashboard built on top of the existing FYERS connection in this repository.

## What it does

- Reads NIFTY 50 and India VIX from FYERS.
- Scans a configurable NSE liquid-stock universe.
- Uses 15-minute candles.
- Calculates EMA20, EMA50, RSI(14), ATR(14), relative volume and 20-bar breakout/breakdown.
- Produces BUY / SELL / WATCH signals.
- Calculates ATR-based entry, stop and two target levels.
- Shows the evidence behind every signal.
- Refreshes automatically every 60 seconds while the page is open.
- Places **no live orders**.

## Run locally

```bash
pip install -r requirements-dashboard.txt
export FYERS_ACCESS_TOKEN='YOUR_TOKEN'
streamlit run dashboard.py
```

The client ID defaults to the existing NIFTY-Straddle FYERS client ID. To override it:

```bash
export FYERS_CLIENT_ID='YOUR_CLIENT_ID'
```

## Streamlit Cloud

Create a Streamlit app using:

- Main file: `dashboard.py`
- Python dependencies: `requirements-dashboard.txt`

In the app's Secrets settings add:

```toml
FYERS_ACCESS_TOKEN = "YOUR_TOKEN"
FYERS_CLIENT_ID = "YOUR_CLIENT_ID"
```

Do not commit the access token to GitHub.

## Signal interpretation

The dashboard's percentage is a **confluence score**, not a probability of profit. A BUY/SELL signal requires a score of +3/-3 or stronger. The next development step is to persist every paper signal and calculate out-of-sample win rate, expectancy, drawdown and performance by setup before considering live execution.
