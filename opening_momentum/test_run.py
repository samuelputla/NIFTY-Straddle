import unittest
from datetime import date, timedelta

from opening_momentum.run import at, opening_features, paper_trade, rank_opening


DAY = date(2026, 11, 16)


def bar(stamp, opening=100, high=100.5, low=99.5, close=100, volume=10):
    return [stamp.timestamp(), opening, high, low, close, volume]


class MomentumTests(unittest.TestCase):
    def test_features_use_only_completed_opening_bars(self):
        bars = []
        for offset in range(20, -1, -1):
            day = DAY - timedelta(days=offset)
            start = at(day, 9, 15)
            bars.extend(bar(start + timedelta(minutes=i * 5), volume=20 if offset == 0 else 10)
                        for i in range(6))
            bars.append(bar(at(day, 15, 25), close=120))
        bars.insert(-1, bar(at(DAY, 9, 45), close=200, volume=10000))
        features = opening_features(bars, DAY)
        self.assertEqual(features["from_open"], 0)
        self.assertEqual(features["relative_volume"], 2)
        self.assertAlmostEqual(features["gap"], 100 / 120 - 1)

    def test_identical_score_uses_symbol_tiebreak(self):
        row = dict(from_open=0.01, gap_held=0.01, relative_volume=2, range_break=0)
        self.assertEqual(rank_opening({"B": row.copy(), "A": row.copy()},
                                      {"B": "Finance", "A": "Finance"}), ["A", "B"])

    def test_same_bar_stop_and_target_uses_stop(self):
        entry = at(DAY, 9, 50)
        bars = [bar(entry + timedelta(minutes=5 * i)) for i in range(68)]
        bars[0] = bar(entry, high=103, low=98)
        _, exit_price, reason, net = paper_trade(bars, entry)
        self.assertEqual((exit_price, reason), (99, "Stop"))
        self.assertAlmostEqual(net, -1.1)

    def test_miss_explains_score_drag_or_tie(self):
        from opening_momentum.review import METRICS, selection_review

        features = {
            symbol: dict.fromkeys(METRICS, 1)
            for symbol in ("A", "B", "C", "D", "E", "F")
        }
        picks = rank_opening(features, dict.fromkeys(features, "Finance"))[:5]
        self.assertIn("tie-break", selection_review("F", features, picks)["reason"])
        features["F"]["relative_volume"] = 0.5
        picks = rank_opening(features, dict.fromkeys(features, "Finance"))[:5]
        review = selection_review("F", features, picks)
        self.assertEqual(review["rank"], 6)
        self.assertIn("relative_volume", review["reason"])

    def test_later_filings_are_kept_out_of_cutoff_evidence(self):
        from opening_momentum.review import evidence_by_cutoff

        cutoff = at(DAY, 9, 45)
        early = {"published_at": at(DAY, 9, 44).isoformat()}
        late = {"published_at": at(DAY, 9, 46).isoformat()}
        review = evidence_by_cutoff({"financial_filings": [early, late]}, cutoff)
        self.assertEqual(review["by_0945"]["financial_filings"], [early])
        self.assertEqual(review["after_0945"]["financial_filings"], [late])
