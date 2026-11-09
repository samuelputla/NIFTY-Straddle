import json
import tempfile
import unittest
from datetime import date,datetime,timedelta
from pathlib import Path
from unittest.mock import patch
from short_term_calls.engine import IST,replay,validate_plan
from short_term_calls.swing import daily_rows,features,make_swing,DEFAULTS,evaluate,next_session,prepare
from short_term_calls.learning import review,challenger_report,market_audit
from short_term_calls.service import install_registry
from short_term_calls.storage import Store,CALLS,STATUS,EVENTS
from test_engine import plan,valid_rows,rows
from test_storage import Book

def history():
    start=date(2026,8,1);data=[]
    for i in range(101):
        d=start+timedelta(days=i)
        if d.weekday()<5 or d==date(2026,11,8):
            close=100+len(data)*.3
            data.append([int(datetime.combine(d,datetime.min.time(),IST).timestamp()),close-.1,close+.5,close-.5,close,1000])
    return data

class SwingTests(unittest.TestCase):
    def test_daily_rejects_stale_duplicate_future_and_invalid_prices(self):
        data=history();through=date(2026,11,9)
        self.assertEqual(daily_rows(data,through),data)
        for bad in (data[:-1],data+[data[-1]],data+[[data[-1][0]+86400,1,2,1,1,1]],data[:-1]+[[data[-1][0],100,99,98,100,1]]):
            with self.assertRaises(ValueError):daily_rows(bad,through)

    def test_special_volume_excluded_but_price_kept(self):
        data=history();data[-2][5]=1;data[-1][5]=2000
        f=features(data)
        self.assertAlmostEqual(f['rvol20_normal'],2)
        data[-2][2]=500
        self.assertEqual(features(data)['resistance'],500)

    def test_no_stock_volume_means_unavailable_not_zero_signal(self):
        data=history();data[-1][5]=0
        with self.assertRaises(ValueError):features(data)

    def test_next_session_skips_holiday(self):
        self.assertEqual(next_session(date(2026,11,9)),date(2026,11,11))

    def test_premarket_and_live_plans_have_distinct_monitor_windows(self):
        f={'symbol':'TEST','resistance':103,'support':100,'ranking_score':1,'archetype':'Continuation',
           'rsi14':60,'rvol20_normal':2,'excess20':2}
        pre=make_swing(f,date(2026,11,11),datetime(2026,11,9,18,tzinfo=IST),DEFAULTS)
        live=make_swing(f,date(2026,11,11),datetime(2026,11,11,10,tzinfo=IST),DEFAULTS,live=True)
        self.assertTrue(pre['monitor_from_start']);self.assertFalse(live['monitor_from_start'])
        self.assertTrue(live['start_at'].startswith('2026-11-11T10:05'))
        self.assertTrue(pre['exit_by'].startswith('2026-11-25'))
        self.assertTrue(live['enter_by'].startswith('2026-11-11T15:00'))
        validate_plan(pre);validate_plan(live)

    def test_frozen_breakout_only_seed_does_not_require_retest(self):
        p=plan(entry_rule='Breakout Confirmation')
        a=rows(45);a[16][1:5]=[100.5,102,100,101]
        r=replay(p,a,'2026-11-09T10:00:00+05:30')
        self.assertTrue(r['entry_at'].startswith('2026-11-09T09:31'))
        self.assertFalse(r['retest_observed'])
        self.assertIsNone(replay(plan(),a,'2026-11-09T10:00:00+05:30')['entry_at'])

    def test_no_expected_prior_session_minutes_for_evening_seed(self):
        p=plan(issued_at='2026-11-06T18:00:00+05:30',monitor_from_start=True)
        r=replay(p,valid_rows(),'2026-11-09T10:15:00+05:30')
        self.assertEqual(r['missing_minutes'],0)

    def test_original_three_seeds_install_once_without_any_provider(self):
        book=Book();store=Store(book);now=datetime(2026,11,9,23,tzinfo=IST)
        install_registry(store,now);install_registry(Store(book),now)
        self.assertEqual(len(book.rows[CALLS]),4)
        self.assertEqual(len(book.rows[STATUS]),4)
        self.assertTrue(all(p['entry_rule']=='Breakout Confirmation' for p in store.plans()))

    def test_late_seed_install_does_not_fabricate_history(self):
        book=Book();install_registry(Store(book),datetime(2026,11,12,8,tzinfo=IST))
        self.assertEqual(len(book.rows[CALLS]),1)
        self.assertEqual(len(book.rows[EVENTS]),4)

    def test_sourced_event_blackout_is_explicit(self):
        data=history()
        f,reasons=evaluate('TEST',data,0,dict(DEFAULTS,rsi_max=100),
           [{'symbol':'TEST','from':'2026-11-11','through':'2026-11-12','source':'Official'}],date(2026,11,11))
        self.assertIn('Known Event Blackout',reasons)
        self.assertEqual(f['event_evidence'][0]['source'],'Official')

class LearningTests(unittest.TestCase):
    def test_stop_review_is_hypothesis_not_automatic_code_change(self):
        p=plan(selection_evidence={'rvol20_normal':1.1,'excess20':-1})
        r={'exit_reason':'Stop','status':'Closed','entry_price':100,'realized_r':-1}
        item=review(p,r)
        self.assertEqual(item['kind'],'Stop Review')
        self.assertIn('Unresolved',item['cause']);self.assertEqual(p['stop'],95)
        self.assertTrue(any('test' in h.lower() for h in item['hypotheses']))

    def test_unfilled_target_is_not_profit(self):
        item=review(plan(),{'status':'Expired Unfilled','entry_price':None,'missed_targets':['T1']})
        self.assertEqual(item['kind'],'Missed Entry Review')
        report=challenger_report([plan()],{'TEST':{'status':'Expired Unfilled','realized_r':2}})
        self.assertTrue(all(x['closed_calls']==0 for x in report['cohorts']))
        self.assertEqual(report['promotion'],'Not Promoted')

    def test_review_journal_retry_is_idempotent(self):
        book=Book();s=Store(book)
        s.journal_once('T','Stop Review','2026-11-11',{'cause':'Unknown'})
        s.journal_once('T','Stop Review','2026-11-12',{'cause':'Unknown'})
        self.assertEqual(len(book.rows[EVENTS]),2)

    def test_missed_leader_does_not_invent_original_formation(self):
        book=Book();store=Store(book)
        fixture={'NEW':{'PrvsClsgPric':'100','ClsPric':'110','TtlTrfVal':'2000000000','FinInstrmNm':'NEW LTD'}}
        Path('.short-term-test-deps').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='.short-term-test-deps') as out,patch('short_term_calls.learning.bhavcopy',return_value=fixture):
            market_audit(store,date(2026,11,11),[],out,datetime(2026,11,11,18,tzinfo=IST))
            result=json.loads((Path(out)/'market-audit-2026-11-11.json').read_text())
        self.assertIn('Formation Unknown',result[0]['coverage'])
        self.assertIn('not executable profit',result[0]['interpretation'])

    def test_unlimited_one_share_selection_has_no_three_call_quota(self):
        from short_term_calls.portfolio import select
        from test_portfolio import candidate
        settings={'initial_capital':300000,'quantity_mode':'one_share','daily_intraday':0,'daily_swing':None}
        selected=select([candidate(i,'Swing') for i in range(12)],[],{},datetime(2026,11,9,18,tzinfo=IST),settings)
        self.assertEqual(sum(x['portfolio_selected'] for x in selected),12)
        self.assertTrue(all(x['quantity']==1 and x['total_costs'] is None for x in selected))

class PreparationTests(unittest.TestCase):
    def test_full_preparation_publishes_all_qualifiers_and_is_idempotent(self):
        now=datetime(2026,11,9,18,tzinfo=IST)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return now
        class Provider:
            def daily(self,symbol,through):return history()
        def evaluated(sym,*args):
            return {'symbol':sym,'close':102,'sma20':100,'sma50':99,'resistance':103,'support':100,
                    'ranking_score':1,'archetype':'Continuation','rsi14':60,'rvol20_normal':2,'excess20':2,
                    'data_through':'2026-11-09'},[]
        config=json.loads(Path('short_term_calls/config.json').read_text())
        candidates=[{'symbol':'STOCK'+str(i),'turnover_cr':200} for i in range(7)]
        book=Book();store=Store(book);Path('.short-term-test-deps').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='.short-term-test-deps') as out,patch('short_term_calls.swing.datetime',Clock),patch('short_term_calls.generate.daily_candidates',return_value=candidates),patch('short_term_calls.swing.evaluate',side_effect=evaluated):
            plans=prepare(store,Provider(),date(2026,11,11),now,out,config)
            again=prepare(Store(book),Provider(),date(2026,11,11),now,out,config)
        self.assertEqual(len(plans),7);self.assertEqual(again,[])
        self.assertEqual(len(book.rows[CALLS]),8);self.assertEqual(len(book.rows[STATUS]),8)
        self.assertTrue(all(p['portfolio_selected'] and p['quantity']==1 for p in plans))

    def test_open_market_generation_rejects_backdated_or_late_forecast(self):
        from short_term_calls.providers import DataUnavailable
        config=json.loads(Path('short_term_calls/config.json').read_text())
        with self.assertRaises(DataUnavailable):
            prepare(Store(Book()),None,date(2026,11,11),datetime(2026,11,11,14,45,tzinfo=IST),'.',config,live=True)
        with self.assertRaises(DataUnavailable):
            prepare(Store(Book()),None,date(2026,11,11),datetime(2026,11,11,9,20,tzinfo=IST),'.',config)

if __name__=='__main__':unittest.main()
