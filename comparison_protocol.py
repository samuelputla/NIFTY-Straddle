"""Frozen comparison protocol. Change version before changing thresholds."""
START='2026-11-02';VERSION='comparison-v1'
CALIBRATION_DAYS=60;HOLDOUT_DAYS=30
RBI_SOURCE='https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62422'
RBI_SCOPE='Scheduled RBI MPC meeting days only; other event types not covered'
RBI_DAYS={'2026-04-06','2026-04-07','2026-04-08','2026-06-03','2026-06-04','2026-06-05','2026-08-03','2026-08-04','2026-08-05','2026-10-05','2026-10-06','2026-10-07','2026-12-02','2026-12-03','2026-12-04','2027-02-03','2027-02-04','2027-02-05'}
def event_day(day):return day in RBI_DAYS if '2026-04-01'<=day<='2027-03-31' else None

def phase_for(n):return 'INCOMPLETE' if not n else 'CALIBRATION' if n<=60 else 'HOLDOUT' if n<=90 else 'POST_HOLDOUT'

