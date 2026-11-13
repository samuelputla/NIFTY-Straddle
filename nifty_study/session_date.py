"""Select the completed study session without inventing a late forecast."""
from datetime import timedelta, time
from .calendar import session

def collection_day(now, scheduled=False):
    # A cron delivered just after midnight belongs to the preceding completed
    # session. The caller still enforces the actual next-session forecast cutoff.
    day = now.date()
    if scheduled and now.time() < time(9,15):
        for _ in range(15):
            day -= timedelta(days=1)
            if session(day): return day.isoformat()
        raise ValueError('No verified prior equity session')
    return day.isoformat()

