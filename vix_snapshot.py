"""Bounded, optional VIX context; never delays option entries."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from quote_quality import quote_prices

SYMBOL = 'NSE:INDIAVIX-INDEX'

def capture_vix(call, sleep=time.sleep, now=lambda: datetime.now(ZoneInfo('Asia/Kolkata'))):
    errors = []
    for attempt in range(3):
        if attempt:
            sleep(2)
        try:
            value = quote_prices(call('quotes', {'symbols': SYMBOL}), [SYMBOL])[SYMBOL]
            return {'value': value, 'at': now().isoformat(), 'attempts': attempt + 1}
        except Exception as error:
            errors.append(type(error).__name__)
    return {'error': ', '.join(errors), 'at': now().isoformat(), 'attempts': 3}

