"""Receipt freshness is distinct from the provider's last-trade timestamp."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
import math
IST = ZoneInfo('Asia/Kolkata')

def trade_timestamp(value):
    try:
        epoch = float(value)
        if not math.isfinite(epoch) or epoch <= 0: return None
        if epoch > 10_000_000_000: epoch /= 1000
        utc = datetime.fromtimestamp(epoch, timezone.utc)
        stamp = utc.astimezone(IST)
        # FYERS may supply a daily date (midnight UTC), not a trade time.
        if utc.time() == time(0) or not time(9,15) <= stamp.time() <= time(15,30): return None
        return stamp
    except (TypeError, ValueError, OSError, OverflowError): return None

def quote_prices(response, symbols):
    if response.get('s') != 'ok': raise RuntimeError('Quote request failed')
    found = {}
    for item in response.get('d', []):
        value = item.get('v', {}).get('lp')
        symbol = item.get('n')
        if item.get('s', 'ok') != 'ok': continue
        if isinstance(value, (int,float)) and math.isfinite(value) and value > 0:
            found[symbol] = value
    if any(symbol not in found for symbol in symbols): raise RuntimeError('Incomplete fresh quote response')
    return {symbol:found[symbol] for symbol in symbols}

