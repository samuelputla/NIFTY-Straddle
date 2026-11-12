"""Recover the 09:30 India VIX reference from the completed FYERS minute."""
from datetime import datetime
from math import isfinite

SYMBOL = "NSE:INDIAVIX-INDEX"
SOURCE = "FYERS 09:30 minute open (historical reference)"


def minute_open(call, day):
    target = int(datetime.fromisoformat(day + "T09:30:00+05:30").timestamp())
    response = call("history", {"symbol": SYMBOL, "resolution": "1",
        "date_format": "1", "range_from": day, "range_to": day, "cont_flag": "0"})
    bars = [bar for bar in response.get("candles", []) if len(bar) >= 6 and bar[0] == target]
    if response.get("s") != "ok" or len(bars) != 1:
        raise RuntimeError("FYERS 09:30 VIX candle unavailable")
    value = float(bars[0][1])
    if not isfinite(value) or value <= 0:
        raise ValueError("Invalid VIX opening value")
    return value
