import unittest
from datetime import datetime
from decimal import Decimal as D

from abc_paper import Candle, IST, Strategy


class PatternTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.strategy = Strategy(lambda event, at, **fields: self.events.append((event, fields)))
        self.at = datetime(2026, 11, 11, 10, tzinfo=IST)
        for low, high, close in [(103, 105, 104), (100, 104, 102), (102, 110, 109)]:
            self.close(low, high, close)

    def close(self, low, high, close):
        self.strategy.close(Candle(D(str(low)), D(str(high)), D(str(close))), self.at)

    def test_wick_at_limit_and_intrabar_break(self):
        self.close(104.8, 109, 105)
        self.assertTrue(self.strategy.armed)
        self.strategy.tick(self.at, D("110"))
        self.assertIsNone(self.strategy.trade)
        self.strategy.tick(self.at, D("110.5"))
        self.assertEqual(self.strategy.trade["entry"], D("110.5"))
        self.assertEqual(self.strategy.trade["target"], D("120.4"))
        self.strategy.tick(self.at, D("104.8"))
        self.assertEqual(self.events[-1][1]["reason"], "stop")
        self.strategy.tick(self.at, D("111"))
        self.assertIsNone(self.strategy.trade)

    def test_deeper_wick_disqualifies(self):
        self.close(104.7, 109, 105)
        self.assertFalse(self.strategy.armed)

    def test_deeper_price_after_arming_disqualifies(self):
        self.close(104.8, 109, 106)
        self.strategy.tick(self.at, D("104.79"))
        self.strategy.tick(self.at, D("111"))
        self.assertIsNone(self.strategy.trade)

    def test_session_exit(self):
        self.close(105, 109, 106)
        self.strategy.tick(self.at, D("111"))
        exit_at = self.at.replace(hour=15)
        self.strategy.exit(exit_at, "session_last_observed_price")
        self.assertEqual(self.events[-1][1]["price"], D("111"))
        self.assertIsNone(self.strategy.trade)


if __name__ == "__main__":
    unittest.main()
