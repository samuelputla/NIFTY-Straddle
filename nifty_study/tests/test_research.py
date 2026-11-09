import json
import unittest
from copy import deepcopy
from nifty_study.run import evaluate
from nifty_study.research import research_history


class ResearchTests(unittest.TestCase):
    def fixture(self):
        actual = [dict(symbol=f'S{i:02}', **{'return': 50-i, 'gap': 1, 'intraday': 2,
            'rvol20': 9, 'breakout': True}) for i in range(50)]
        forecast = [{'Forecast ID': 'f', 'Target Session': '2026-11-11',
            'Symbol': r['symbol'], 'Selected': str(5 <= i < 10),
            'Created At': '2026-11-09T21:30:00+05:30', 'Rule Version': 'v1',
            'Rank': str((i-5) % 50+1), 'Score': str(50-((i-5) % 50)),
            'Reasons': json.dumps({'features': {'rvol20': i+1}, 'score_parts': {'rvol20': .2}}),
            'Baseline Prior Winner Rank': str(i+1), 'Baseline Momentum Rank': str(i+1),
            'Baseline Sector Rank': str(i+1)} for i, r in enumerate(actual)]
        return actual, forecast

    def test_misses_compare_frozen_inputs_without_leaking_outcomes(self):
        actual, forecast = self.fixture()
        original = deepcopy(forecast)
        reviews, changes, summary = evaluate(forecast, actual, '2026-11-11', 'key')
        self.assertEqual(forecast, original)
        self.assertEqual(len(changes), 10)
        self.assertEqual(summary[0]['precision_at_5'], 0)
        missed = json.loads(reviews[0][10])
        self.assertEqual(missed['outcome'], 'MISSED LEADER')
        comparison = missed['known_before_session']['feature_comparison']['rvol20']
        self.assertEqual(comparison, {'frozen_value': 1, 'selected_median': 8, 'difference': -7})
        self.assertEqual(missed['observed_during_session']['rvol20'], 9)
        self.assertLess(missed['known_before_session']['score_gap_to_cutoff'], 0)
        self.assertIn('Unresolved', missed['cause'])

    def test_history_deduplicates_and_excludes_incomplete_forecasts(self):
        actual, forecast = self.fixture()
        reviews, _, _ = evaluate(forecast, actual, '2026-11-11', 'key')
        self.assertEqual(research_history([], reviews[:-1]), {})
        history = research_history([], reviews+reviews)
        self.assertEqual(history['v1']['evaluated_forecasts'], 1)
        self.assertEqual(history['v1']['total_picks'], 5)
        self.assertEqual(len(history['v1']['sessions'][0]['missed_leaders']), 5)
        self.assertEqual(len(history['v1']['sessions'][0]['failed_picks']), 5)

    def test_legacy_missing_feature_details_stay_unavailable(self):
        actual, forecast = self.fixture()
        for row in forecast:
            row['Reasons'] = 'unavailable'
        reviews, _, _ = evaluate(forecast, actual, '2026-11-11', 'key')
        self.assertEqual(json.loads(reviews[0][10])['known_before_session']['feature_comparison'], {})


if __name__ == '__main__':
    unittest.main()

