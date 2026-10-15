"""Offline scenarios: importing the strategy never connects to FYERS/Sheets."""
import copy
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import weekly_strangle as w
from weekly_rules import fresh_pair, inward_strike, valid_price


class Table:
    def __init__(self, rows=None): self.rows = rows or []
    def get_all_values(self): return copy.deepcopy(self.rows)
    def append_row(self, row, **kwargs): self.rows.append(copy.deepcopy(row))


class WeeklyScenarios(unittest.TestCase):
    def setUp(self):
        self.stamp = datetime(2026, 10, 15, 10, 0, tzinfo=w.IST)
        clock = patch.object(w, 'now_ist', side_effect=lambda: self.stamp)
        clock.start()
        self.addCleanup(clock.stop)
        w.COST_PROFILE = {'id': 'test-flat-75', 'cost_per_execution': 75}
        w.sheet_tab = Table([w.HEADERS])
        w.log_tab = Table([w.LOG_HEADERS])
        w.cycle = w.pending_entry = w.prepared_expiry = None
        w.last_adjustment_at = w.last_write_at = w.last_refresh_at = None
        w.next_action_retry_at = None
        w.latest.clear()
        w.latest_at.clear()
        w.observed_ranges.clear()
        w.last_notice.clear()
        w.stop_event.clear()
        w.socket_holder['socket'] = None
        w.END_TIME = w.time(15, 30)
        w.PROFITABLE_ADJUSTMENTS_ONLY = False

    def cycle(self, ce_credit=100, pe_credit=98, ce_ltp=220, pe_ltp=93):
        s = w.make_cycle('1792404600', '19-10-2026',
            {'symbol': 'CE', 'strike': 23000, 'ltp': ce_credit},
            {'symbol': 'PE', 'strike': 22000, 'ltp': pe_credit},
            'TEST ENTRY', self.stamp, 'test')
        for side in ('CE', 'PE'):
            w.record_position_event(s, 'CYCLE ENTRY', 'SELL TO OPEN', side, side,
                                    s['legs'][side]['ltp'], 'TEST')
        s['legs']['CE']['ltp'] = ce_ltp
        s['legs']['PE']['ltp'] = pe_ltp
        return s

    def roll(self, s, new=200, strike=22500, low=93, high=220):
        with patch.object(w, 'option_chain', return_value={'optionsChain': [
            {'symbol': 'NEWPE', 'option_type': 'PE', 'ltp': 200, 'strike_price': strike}]}), \
             patch.object(w, 'quote', return_value={'CE': high, 'PE': low, 'NEWPE': new}):
            w.roll_low_leg(s, '50% DIVERGENCE')

    def test_invalid_prices(self):
        for price in (None, 0, -1, float('nan'), float('inf')):
            self.assertFalse(valid_price(price))

    def test_inward_move_and_no_crossing(self):
        self.assertTrue(inward_strike('PE', 22000, 22500, 23000))
        self.assertTrue(inward_strike('CE', 23000, 22000, 22000))
        self.assertFalse(inward_strike('PE', 22000, 23100, 23000))
        self.assertFalse(inward_strike('CE', 23000, 23100, 22000))

    def test_missing_strike_not_guessed(self):
        self.assertIsNone(w.strike_for_leg({'symbol': 'NSE:NIFTY26O1922500PE'}))

    def test_entry_band_required(self):
        with self.assertRaises(RuntimeError):
            w.choose_entry_candidate([{'ltp': 26}, {'ltp': 19}])
        self.assertEqual(w.choose_entry_candidate([{'ltp': 21}, {'ltp': 24.9}])['ltp'], 24.9)

    def test_holiday_and_monthly_listed_expiry(self):
        data = {'expiryData': [
            {'date': '19-10-2026', 'expiry': '100', 'expiry_flag': 'W'},
            {'date': '27-10-2026', 'expiry': '200', 'expiry_flag': 'M'}]}
        self.assertEqual(w.expiry_options(data, after_date=self.stamp.date())[0], '100')
        self.assertEqual(w.expiry_options(data, '100')[0], '200')

    def test_pair_freshness_and_skew(self):
        prices = {'CE': 100, 'PE': 50}
        self.assertTrue(fresh_pair(list(prices), prices, dict.fromkeys(prices, self.stamp), self.stamp))
        self.assertFalse(fresh_pair(list(prices), prices,
            {'CE': self.stamp, 'PE': self.stamp-timedelta(seconds=3)}, self.stamp))
        self.assertFalse(fresh_pair(list(prices), prices,
            dict.fromkeys(prices, self.stamp-timedelta(seconds=6)), self.stamp))

    def test_costs_reserve_open_exits(self):
        s = self.cycle(100, 100, 75, 75)
        self.assertEqual(s['estimated_paid_costs'], 150)
        self.assertEqual(w.p_and_l(s), (50, 50, 2950))
        self.assertEqual(w.NET_PROFIT_TARGET_RUPEES, 2500)
        self.assertGreater(w.p_and_l(s)[2], w.NET_PROFIT_TARGET_RUPEES)

    def test_lower_premium_can_realize_loss(self):
        s = self.cycle(pe_credit=80)
        self.roll(s)
        self.assertEqual(s['realized_points'], -13)
        self.assertEqual(s['legs']['CE']['symbol'], 'CE')
        self.assertEqual(s['legs']['PE']['symbol'], 'NEWPE')
        self.assertEqual(s['estimated_paid_costs'], 300)

    def test_fresh_quote_outside_band_aborts(self):
        s = self.cycle()
        self.roll(s, new=215)
        self.assertEqual(s['adjustment_count'], 0)
        self.assertEqual(s['estimated_paid_costs'], 150)

    def test_reversed_divergence_aborts(self):
        s = self.cycle()
        self.roll(s, low=230, high=220)
        self.assertEqual(s['adjustment_count'], 0)

    def test_crossed_strike_not_selected(self):
        s = self.cycle()
        self.roll(s, strike=23100)
        self.assertEqual(s['adjustment_count'], 0)

    def test_straddle_reference_uses_current_marks(self):
        s = self.cycle()
        self.roll(s, strike=23000)
        self.assertEqual(s['phase'], 'STRADDLE')
        self.assertEqual(s['straddle_credit'], 420)
        self.assertFalse(w.should_roll(s, self.stamp))
        self.assertNotEqual(s['straddle_credit'], 300)

    def test_eod_requires_more_than_eighty_percent(self):
        s = self.cycle(ce_ltp=100, pe_ltp=20)
        self.assertTrue(w.should_roll(s, self.stamp))
        self.stamp = self.stamp.replace(hour=15, minute=25)
        self.assertFalse(w.should_roll(s, self.stamp))
        s['legs']['PE']['ltp'] = 19.9
        self.assertTrue(w.should_roll(s, self.stamp))

    def test_stop_queues_next_expiry_immediately(self):
        s = self.cycle()
        s['legs']['PE']['strike'] = 23000
        s.update(phase='STRADDLE', straddle_credit=250,
                 straddle_reference_basis='paired premiums at formation')
        w.cycle = s
        with patch.object(w, 'refresh_active', return_value=True), \
             patch.object(w, 'quote', return_value={'CE': 220, 'PE': 93}):
            w.process_tick_actions()
        self.assertIsNone(w.cycle)
        self.assertEqual(w.pending_entry[0], '1792404600')
        self.assertIn('10% STRADDLE', w.pending_entry[1])
        saved = w.json.loads(w.sheet_tab.rows[-1][29])
        self.assertEqual(saved['status'], 'CLOSED')
        self.assertEqual(saved['pending_entry']['after_expiry'], '1792404600')
        self.assertEqual(saved['estimated_paid_costs'], 300)

    def test_target_rechecked_before_exit(self):
        s = self.cycle(100, 100, 70, 70)
        w.cycle = s
        with patch.object(w, 'quote', return_value={'CE': 80, 'PE': 80}):
            w.perform_cycle_exit('₹2,500 NET CYCLE PROFIT TARGET', True)
        self.assertIs(w.cycle, s)
        self.assertEqual(s['status'], 'ACTIVE')
        self.assertNotIn('pending_exit', s)
        self.assertEqual(s['estimated_paid_costs'], 150)

    def test_rollover_uses_actual_monday(self):
        self.stamp = datetime(2026, 10, 19, 9, 30, tzinfo=w.IST)
        w.cycle = self.cycle()
        with patch.object(w, 'refresh_active', return_value=True), \
             patch.object(w, 'perform_cycle_exit') as ex:
            w.process_tick_actions()
        ex.assert_called_once_with('EXPIRY ROLLOVER', True)

    def test_stale_data_cannot_trigger_action(self):
        w.cycle = self.cycle()
        with patch.object(w, 'refresh_active', return_value=False), \
             patch.object(w, 'perform_cycle_exit') as ex, patch.object(w, 'roll_low_leg') as roll:
            w.process_tick_actions()
        ex.assert_not_called()
        roll.assert_not_called()

    def test_cutoff_prevents_action(self):
        self.stamp = self.stamp.replace(hour=15, minute=30)
        w.cycle = self.cycle()
        with patch.object(w, 'refresh_active') as refresh:
            w.process_tick_actions()
        refresh.assert_not_called()

    def test_delayed_response_cannot_roll_after_cutoff(self):
        s = self.cycle()
        def quote(_):
            self.stamp = self.stamp.replace(hour=15, minute=30)
            return {'CE': 220, 'PE': 93, 'NEWPE': 200}
        with patch.object(w, 'option_chain', return_value={'optionsChain': [
            {'symbol': 'NEWPE', 'option_type': 'PE', 'ltp': 200, 'strike_price': 22500}]}), \
             patch.object(w, 'quote', side_effect=quote):
            w.roll_low_leg(s, 'TEST')
        self.assertEqual(s['adjustment_count'], 0)

    def test_socket_tick_cannot_mutate_decision_state(self):
        w.cycle = self.cycle()
        w.on_message({'symbol': 'CE', 'ltp': 999})
        self.assertEqual(w.latest['CE'], 999)
        self.assertEqual(w.cycle['legs']['CE']['ltp'], 220)

    def test_commit_events_and_idempotent_retry(self):
        s = self.cycle()
        pending = copy.deepcopy(s['pending_events'])
        w.log_state(s, 'ENTRY')
        self.assertEqual(len(w.log_tab.rows), 3)
        persisted = w.json.loads(w.sheet_tab.rows[-1][29])
        self.assertEqual(persisted['pending_events'], pending)
        w.flush_events(persisted)
        self.assertEqual(len(w.log_tab.rows), 3)

    def test_ambiguous_state_write_is_fatal(self):
        s = self.cycle()
        with patch.object(w.sheet_tab, 'append_row', side_effect=TimeoutError):
            with self.assertRaises(w.PersistenceError): w.log_state(s, 'ENTRY')
        self.assertEqual(len(w.log_tab.rows), 1)

    def test_bad_latest_state_not_skipped(self):
        s = self.cycle()
        w.sheet_tab.rows.extend([w.snapshot_row(s), ['']*29+['{bad']])
        with self.assertRaises(RuntimeError): w.load_latest_state()

    def test_legacy_cost_migration(self):
        s = self.cycle()
        w.log_state(s)
        s.pop('cost_profile')
        s.pop('estimated_paid_costs')
        self.assertTrue(w.migrate_costs(s))
        self.assertEqual(s['estimated_paid_costs'], 150)
        self.assertFalse(w.migrate_costs(s))

    def test_incomplete_legacy_ledger_rejected(self):
        s = self.cycle()
        s.pop('cost_profile')
        with self.assertRaises(RuntimeError): w.migrate_costs(s)

    def test_next_cycle_can_enter_before_930_after_carried_stop(self):
        self.stamp = self.stamp.replace(hour=9, minute=20)
        expiry = {'expiryData': [{'date': '27-10-2026', 'expiry': '1793095800'}]}
        contracts = {'CE': {'symbol': 'NEXTCE', 'strike': 23000, 'ltp': 25},
                     'PE': {'symbol': 'NEXTPE', 'strike': 22000, 'ltp': 24}}
        with patch.object(w, 'option_chain', return_value=expiry), \
             patch.object(w, 'target_contracts', return_value=contracts):
            s = w.start_cycle('1792404600', 'NEW CYCLE AFTER STOP')
        self.assertEqual(s['expiry'], '27-10-2026')
        self.assertEqual(s['start_time'], '2026-10-15 09:20:00')
        self.assertEqual(s['estimated_paid_costs'], 150)

    def test_actual_audited_cycle_net_after_flat_costs(self):
        s = self.cycle(97.25, 54.65, 103.8, 87.65)
        s['realized_points'] = 37.15
        s['estimated_paid_costs'] = 12*75
        self.assertEqual(w.p_and_l(s), (-39.55, -2.4, -1206))

    def test_reconnect_clears_cached_prices(self):
        w.latest['CE'] = 100
        w.latest_at['CE'] = self.stamp
        from unittest.mock import Mock
        w.socket_holder['socket'] = Mock()
        w.on_open()
        self.assertEqual(w.latest, {})
        self.assertEqual(w.latest_at, {})

    def test_restore_closed_state_never_revives_previous_active(self):
        s = self.cycle()
        w.log_state(s)
        closed = copy.deepcopy(s)
        closed['status'] = 'CLOSED'
        w.log_state(closed)
        self.assertIsNone(w.load_state())

    def test_market_failure_preserves_exit_intent(self):
        s = self.cycle()
        w.cycle = s
        with patch.object(w, 'quote', side_effect=w.MarketDataError):
            with self.assertRaises(w.MarketDataError):
                w.perform_cycle_exit('10% STRADDLE COMBINED PREMIUM STOP', True)
        saved = w.json.loads(w.sheet_tab.rows[-1][29])
        self.assertEqual(saved['pending_exit'], '10% STRADDLE COMBINED PREMIUM STOP')
        self.assertEqual(saved['status'], 'ACTIVE')
        self.assertEqual(saved['estimated_paid_costs'], 150)


if __name__ == '__main__': unittest.main()
