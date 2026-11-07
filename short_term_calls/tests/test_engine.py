import unittest
from datetime import datetime,timedelta
from short_term_calls.engine import IST,replay,candles,validate_plan,session
from short_term_calls.generate import make_plan,DEFAULTS


def plan(**changes):
    p=dict(id='TEST',symbol='NSE:TEST-EQ',type='Intraday',status='Active',
        issued_at='2026-11-09T09:14:00+05:30',start_at='2026-11-09T09:15:00+05:30',
        enter_by='2026-11-09T12:30:00+05:30',exit_by='2026-11-09T15:00:00+05:30',
        observe_until='2026-11-11T15:30:00+05:30',trigger=100,entry_min=100,entry_max=101,
        stop=95,target_1=110,target_2=120,quantity=None,total_costs=None,
        source='Synthetic Test',rationale='Test only',policy='Full Exit At T1')
    p.update(changes);return p


def rows(count=60):
    at=datetime(2026,11,9,9,15,tzinfo=IST)
    return [[int((at+timedelta(minutes=i)).timestamp()),102,103,102,102,100] for i in range(count)]


def valid_rows(count=60):
    a=rows(count)
    for i in range(15,30):a[i][1:5]=[102,103,100.5,100.5]
    a[30][1:5]=[100.5,102,100,101]
    return a


def evaluate(a,p=None):
    end=datetime.fromtimestamp(a[-1][0],IST)+timedelta(minutes=1) if a else datetime(2026,11,9,10,15,tzinfo=IST)
    return replay(p or plan(),a,end.isoformat())


class EntryTests(unittest.TestCase):
    def test_breakout_does_not_double_as_retest(self):
        a=rows(16)
        for r in a[:15]:r[1:5]=[100.5,102,100,100.5]
        self.assertIsNone(evaluate(a)['entry_at'])

    def test_later_red_retest_and_confirmation(self):
        r=evaluate(valid_rows())
        self.assertEqual(r['entry_price'],'100.5')
        self.assertTrue(r['entry_at'].startswith('2026-11-09T09:45:'))

    def test_close_at_trigger_fails(self):
        a=valid_rows()
        for r in a[15:30]:r[1:5]=[102,103,99,100]
        self.assertIsNone(evaluate(a)['entry_price'])

    def test_confirmation_above_band_fails(self):
        a=valid_rows()
        for r in a[15:30]:r[1:5]=[102,103,100.5,102]
        self.assertIsNone(evaluate(a)['entry_price'])

    def test_next_open_above_band_no_chase(self):
        a=valid_rows();a[30][1:5]=[103,104,102,103]
        self.assertIsNone(evaluate(a)['entry_price'])

    def test_stop_before_entry_cancels(self):
        a=valid_rows();a[2][3]=94
        self.assertEqual(evaluate(a)['status'],'Cancelled')

    def test_stop_after_issue_before_signal_window_still_cancels(self):
        a=valid_rows();a[1][3]=94
        r=evaluate(a,plan(start_at='2026-11-09T09:20:00+05:30'))
        self.assertEqual(r['status'],'Cancelled');self.assertIsNone(r['entry_at'])

    def test_breakout_before_signal_window_does_not_qualify(self):
        r=evaluate(rows(15),plan(start_at='2026-11-09T09:20:00+05:30'))
        self.assertIsNone(r['breakout'])

    def test_missing_minute_blocks_entry(self):
        a=valid_rows();del a[12]
        r=evaluate(a)
        self.assertEqual(r['status'],'Data Incomplete');self.assertIsNone(r['entry_at'])

    def test_target_without_retest_is_no_trade(self):
        a=rows(45);a[20][2]=111
        r=evaluate(a)
        self.assertIsNone(r['gross_per_share'])
        self.assertTrue(any(e['kind']=='Missed T1' and e['detail'].startswith('Breakout Without Retest') for e in r['events']))

    def test_retest_and_target_same_minute_ambiguous_observation(self):
        a=rows(45);a[20][2:4]=[111,100.5]
        r=evaluate(a)
        self.assertTrue(any('Ordering Unknown' in e['detail'] for e in r['events']))


class AccountingTests(unittest.TestCase):
    def test_target_after_entry_and_explicit_costs(self):
        a=valid_rows();a[32][2]=111
        r=evaluate(a,plan(quantity=10,total_costs=5))
        self.assertEqual(r['gross_per_share'],'9.5');self.assertEqual(r['net_pnl'],'90.0')

    def test_unknown_quantity_and_costs_not_invented(self):
        a=valid_rows();a[32][2]=111
        r=evaluate(a)
        self.assertIsNone(r['net_pnl']);self.assertIsNone(r['gross_pnl'])

    def test_gap_stop_worse_than_threshold(self):
        a=valid_rows();a[32][1:5]=[90,93,89,92]
        r=evaluate(a);self.assertEqual(r['exit_price'],'90');self.assertEqual(r['exit_reason'],'Gap Stop')

    def test_same_minute_stop_target_unknown(self):
        a=valid_rows();a[32][2:4]=[111,94]
        r=evaluate(a);self.assertEqual(r['status'],'Review Required');self.assertIsNone(r['gross_per_share'])

    def test_exit_then_target_does_not_rewrite_pnl(self):
        a=valid_rows(375)
        # No stop or target until the 15:00 deadline, then next minute reaches both targets.
        a[345][1:5]=[105,106,104,105]
        a[346][1:5]=[105,121,104,110]
        r=evaluate(a)
        self.assertEqual(r['gross_per_share'],'4.5')
        self.assertIn('T2',r['post_exit_touches'])

    def test_gap_after_entry_withholds_pnl(self):
        a=valid_rows();del a[31];a[32][2]=111
        r=evaluate(a);self.assertEqual(r['status'],'Review Required');self.assertIsNone(r['gross_per_share'])

    def test_expired_setup_no_retroactive_entry(self):
        a=valid_rows(375)
        p=plan(enter_by='2026-11-09T09:44:00+05:30')
        r=evaluate(a,p);self.assertEqual(r['status'],'Expired Unfilled');self.assertIsNone(r['entry_at'])

    def test_preliminary_plan_cannot_trade(self):
        r=evaluate(valid_rows(),plan(status='Needs Revalidation'))
        self.assertEqual(r['status'],'Needs Revalidation');self.assertIsNone(r['entry_at'])


class EvidenceTests(unittest.TestCase):
    def test_incomplete_minute_discarded(self):
        a=rows(1)
        self.assertEqual(candles(a,datetime.fromtimestamp(a[0][0]+30,IST)),[])

    def test_conflicting_duplicate_rejected(self):
        a=rows(1);b=list(a[0]);b[4]=102.5
        with self.assertRaises(ValueError):candles(a+[b],datetime(2026,11,9,10,tzinfo=IST))

    def test_unknown_calendar_fails_closed(self):
        with self.assertRaises(ValueError):session(datetime(2027,1,4).date())

    def test_holiday_closed(self):
        self.assertFalse(session(datetime(2026,11,10).date()))

    def test_no_lookahead_future_minutes(self):
        self.assertEqual(candles(rows(10),datetime(2026,11,9,9,15,tzinfo=IST)),[])

    def test_risk_and_quantity_validation(self):
        with self.assertRaises(ValueError):validate_plan(plan(stop=102))
        with self.assertRaises(ValueError):validate_plan(plan(quantity=-1))


class GenerationTests(unittest.TestCase):
    def candidate(self):
        return dict(symbol='TEST',high=103,support=100,turnover_cr=200,recent_relative_volume=1.2)

    def test_plan_is_prospective_and_explicit(self):
        a=rows(35)
        for r in a:r[1:5]=[102,103,100,102]
        now=datetime(2026,11,9,9,50,tzinfo=IST)
        p=make_plan(self.candidate(),'Intraday',a,now,dict(DEFAULTS,intraday_max_risk_pct=5))
        self.assertIsNotNone(p);self.assertGreater(p['start_at'],p['issued_at'])
        self.assertEqual(p['quantity'],1);self.assertEqual(p['policy'],'Full Exit At T1')

    def test_missing_opening_minutes_no_call(self):
        self.assertIsNone(make_plan(self.candidate(),'Swing',rows(20),datetime(2026,11,9,9,50,tzinfo=IST),DEFAULTS))

    def test_chasing_already_extended_stock_no_call(self):
        a=rows(35);a[-1][4]=120
        self.assertIsNone(make_plan(self.candidate(),'Swing',a,datetime(2026,11,9,9,50,tzinfo=IST),DEFAULTS))


if __name__=='__main__':unittest.main()
