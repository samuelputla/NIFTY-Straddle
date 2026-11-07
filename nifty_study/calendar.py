"""Capital-market calendar, explicitly bounded; never reuse F&O calendar."""
from datetime import date, timedelta

SOURCES = ['https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf',
           'https://nsearchives.nseindia.com/content/circulars/CMTR76941.pdf']
HOLIDAYS = set('2026-01-26 2026-03-03 2026-03-26 2026-03-31 2026-04-03 2026-04-14 2026-05-01 2026-05-28 2026-06-26 2026-09-14 2026-10-02 2026-10-20 2026-11-10 2026-11-24 2026-12-25'.split())

def session(day):
    day = date.fromisoformat(str(day))
    if day.year != 2026:
        raise ValueError('Equity calendar outside verified 2026; update required')
    if str(day) == '2026-11-08':
        return {'open': '14:20', 'close': '15:30', 'kind': 'MUHURAT'}
    if day.weekday() >= 5 or str(day) in HOLIDAYS:
        return None
    return {'open': '09:15', 'close': '15:30', 'kind': 'NORMAL'}

def next_session(day):
    day = date.fromisoformat(str(day))
    for _ in range(15):
        day += timedelta(days=1)
        if session(day):
            return str(day)
    raise ValueError('Next session not verified')
