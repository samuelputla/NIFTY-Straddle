"""Normal NSE F&O sessions from the verified 2026 exchange calendar."""
from datetime import date
SOURCE='https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf'
# This installation starts 30 October. Fail closed outside the verified period.
CLOSURES={'2026-10-20','2026-11-10','2026-11-24','2026-12-25'}
def session_allowed(day):
 day=date.fromisoformat(str(day))
 if not date(2026,10,7)<=day<=date(2026,12,31):
  return False,'Calendar outside verified 7 October–31 December 2026 period; update required'
 if day.weekday()>=5:return False,'Weekend; special sessions are not enabled'
 if day.isoformat() in CLOSURES:return False,'NSE F&O trading holiday'
 return True,'Normal weekday session'

