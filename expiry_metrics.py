"""Calendar DTE for paper-strategy records; no market/API side effects."""
from datetime import date, datetime

def calendar_dte(session_date, expiry_date):
    def parsed(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(str(value), fmt).date()
            except ValueError:
                pass
        raise ValueError("Invalid session or expiry date for DTE")
    result = (parsed(expiry_date) - parsed(session_date)).days
    if result < 0:
        raise ValueError("Expiry precedes session date")
    return result

def choose_monthly_date(session_date, listed_dates, futures_dates, option_dates):
    available = sorted(day for day in futures_dates if day >= session_date)
    if not available:
        raise ValueError("No current monthly NIFTY futures expiry")
    chosen = available[0]
    if chosen not in listed_dates or chosen not in option_dates:
        raise ValueError("Monthly expiry not cross-verified in option metadata and master")
    return chosen
