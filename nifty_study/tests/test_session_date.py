import unittest
from datetime import datetime
from nifty_study.session_date import collection_day

class SessionDateTests(unittest.TestCase):
    def test_delayed_cron_uses_previous_completed_session(self):
        self.assertEqual(collection_day(datetime.fromisoformat('2026-11-13T00:10:00+05:30'),True),'2026-11-12')
    def test_manual_morning_does_not_backdate(self):
        self.assertEqual(collection_day(datetime.fromisoformat('2026-11-13T08:00:00+05:30')),'2026-11-13')
    def test_weekend_and_holiday(self):
        self.assertEqual(collection_day(datetime.fromisoformat('2026-11-11T01:00:00+05:30'),True),'2026-11-09')
    def test_evening_stays_today(self):
        self.assertEqual(collection_day(datetime.fromisoformat('2026-11-13T16:30:00+05:30'),True),'2026-11-13')

