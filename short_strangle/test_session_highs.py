import unittest

from short_strangle.engine import HIGH_RECONCILED, QUOTE_GAP, Scenario


class SessionHighTests(unittest.TestCase):
    def setUp(self):
        self.day = '2026-11-12'
        self.scenario = Scenario(self.day, 1, 'Current Week', '2026-11-17', 10,
                                 25323, '', {'CE': 'CE', 'PE': 'PE'})
        self.scenario.enter({'CE': 100, 'PE': 100}, self.day + 'T09:30:02+05:30')
        self.scenario.finish({'CE': 90, 'PE': 90}, self.day + 'T15:00:00+05:30')
        self.scenario.issue(QUOTE_GAP)

    def evidence(self, side, high, minutes=330):
        row = [''] * 33
        row[8:11] = [side, self.scenario.entry_at, 110]
        row[14] = self.day + 'T15:00:00+05:30'
        row[20:25] = [self.day + 'T10:00:00+05:30', minutes, 330,
                      'COMPLETE MINUTE BARS' if minutes == 330 else 'PARTIAL MINUTE BARS', high]
        row[28] = 100
        return row

    def test_crossing_replaces_close_at_stop_and_clears_verified_gap(self):
        for high in (110, 111):
            with self.subTest(high=high):
                self.setUp()
                self.assertTrue(self.scenario.reconcile_session_highs({
                    'CE': self.evidence('CE', high), 'PE': self.evidence('PE', 109)}))
                self.assertEqual(self.scenario.exits['CE'][0], 110)
                self.assertEqual(self.scenario.exits['PE'][0], 90)
                self.assertEqual(self.scenario.net, -150)
                self.assertNotIn(QUOTE_GAP, self.scenario.notes)
                self.assertTrue(any(HIGH_RECONCILED in n for n in self.scenario.notes))

    def test_partial_below_stop_keeps_gap_and_preserves_existing_stop(self):
        self.scenario.exits['CE'] = (110, self.day + 'T09:32:00+05:30', 'SL threshold paper fill')
        self.assertFalse(self.scenario.reconcile_session_highs({
            'CE': self.evidence('CE', 115), 'PE': self.evidence('PE', 109, 329)}))
        self.assertIn(QUOTE_GAP, self.scenario.notes)
        self.assertEqual(self.scenario.exits['CE'][1], self.day + 'T09:32:00+05:30')
