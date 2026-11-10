import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from option_observations import Observer, candle_high, ENTRY_HEADERS, HIGH_HEADERS

DAY='2026-11-11'
AT=DAY+'T09:30:00+05:30'

class Observations(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=__import__('os').getcwd())
        self.cwd=patch('option_observations.Path',side_effect=lambda p:__import__('pathlib').Path(self.temp.name)/p)
        self.cwd.start()
        self.o=Observer(None,None,DAY,'test',enabled=False)
        self.o.enabled=True
        self.o._request=lambda m,p:self.request(m,p)
        self.o.cache['expiries']=[{'expiry':int(datetime.fromisoformat(DAY+'T15:30:00+05:30').timestamp())}]
        self.requests=[]

    def tearDown(self):
        self.o.pool.shutdown(wait=True);self.cwd.stop();self.temp.cleanup()

    def request(self,method,payload):
        self.requests.append((method,payload))
        if method=='optionchain':return {'s':'ok','data':{'callOi':1000,'putOi':2000,'optionsChain':[{'symbol':'CE','oi':100,'greeks':{'delta':.5,'gamma':.01,'theta':-10,'vega':8,'iv':15}}]}}
        if method=='depth':return {'s':'ok','d':{'CE':{'bids':[{'price':99,'volume':65}],'ask':[{'price':101,'volume':130}]}}}
        return {'s':'error'}

    def register(self,pct=25,entry=AT):
        self.o.register('Time Based','Current Week',DAY,pct,1,'CE','CE',entry,100,100*(1+pct/100))
        for f in list(self.o.futures):f.result()

    def test_entry_fields_and_alternative_deduplication(self):
        self.register();self.register(30)
        entries,highs=self.o.rows();r=dict(zip(ENTRY_HEADERS,entries[0]))
        self.assertEqual(r['Gamma'],.01);self.assertEqual(r['Theta'],-10)
        self.assertEqual(r['IV'],15);self.assertEqual(r['Spread'],2)
        self.assertEqual(r['Chain CE OI Total'],1000)
        self.assertEqual(len([x for x in self.requests if x[0]=='depth']),1)
        self.assertEqual(len(entries[0]),len(ENTRY_HEADERS));self.assertEqual(len(highs[0]),len(HIGH_HEADERS))

    def test_full_window_high_continues_after_exit_without_false_stop(self):
        self.register()
        self.o.exited('Time Based','Current Week',25,1,'CE',DAY+'T11:20:00+05:30','TIME RESET')
        self.o.tick('CE',180,DAY+'T13:00:00+05:30')
        self.o.tick('CE',900,DAY+'T15:01:00+05:30')
        r=dict(zip(HIGH_HEADERS,self.o.rows()[1][0]))
        self.assertEqual(r['Observed High'],180)
        self.assertTrue(r['Full Window High At Or Above Stop'])
        self.assertEqual(r['Observed Crossing While Leg Open'],'')

    def test_preentry_crossing_is_not_an_open_leg_stop(self):
        self.o.tick('CE',180,AT)
        self.register(entry=DAY+'T11:20:00+05:30')
        r=dict(zip(HIGH_HEADERS,self.o.rows()[1][0]))
        self.assertEqual(r['Observed High'],180)
        self.assertEqual(r['Observed Crossing While Leg Open'],'')

    def test_stop_crossing_recorded_while_open(self):
        self.register();self.o.tick('CE',126,DAY+'T10:00:00+05:30')
        r=dict(zip(HIGH_HEADERS,self.o.rows()[1][0]))
        self.assertEqual(r['Observed Crossing While Leg Open'],DAY+'T10:00:00+05:30')

    def test_jump_over_stop_is_a_loss_for_every_option_family(self):
        for family in ('Fixed Entry','Time Based','Delta Based','Short Strangle'):
            self.o.register(family,'Current Week',DAY,25,1,'CE','CE',AT,80,100)
        for f in list(self.o.futures):f.result()
        self.o.tick('CE',101,DAY+'T10:00:00+05:30')
        for row in self.o.rows()[1]:
            r=dict(zip(HIGH_HEADERS,row))
            self.assertTrue(r['Holding Window High At Or Above Stop'])
            self.assertEqual(r['Paper SL Loss INR'],-1300)

    def test_historical_high_only_counts_inside_actual_holding_interval(self):
        self.register(entry=DAY+'T11:20:02+05:30')
        start=int(datetime.fromisoformat(DAY+'T11:20:00+05:30').timestamp())
        self.o.history['CE']=[[start-60,100,150,90,100,1],[start,100,150,90,100,1],[start+60,100,126,90,100,1]]
        self.o.exited('Time Based','Current Week',25,1,'CE',DAY+'T11:22:00+05:30','TIME RESET')
        r=dict(zip(HIGH_HEADERS,self.o.rows()[1][0]))
        self.assertEqual(r['Holding Window Candle High'],126)
        self.assertTrue(r['Holding Window High At Or Above Stop'])

    def test_missing_greeks_and_crossed_depth_are_not_invented(self):
        self.register();key=next(iter(self.o.snapshots));self.o.snapshots[key]['option']={}
        self.o.snapshots[key]['depth']={'bids':[{'price':105}],'ask':[{'price':100}]}
        r=dict(zip(ENTRY_HEADERS,self.o.rows()[0][0]))
        self.assertEqual(r['IV'],'');self.assertEqual(r['Spread'],'')
        self.assertIn('Crossed book',r['Data Status'])

    def test_context_uses_actual_previous_session_and_today_open(self):
        def data(m,p):return {'s':'ok','candles':[[int(datetime.fromisoformat(d+'T00:00:00+05:30').timestamp()),o,110,90,100,5] for d,o in [('2026-11-09',95),(DAY,101)]]}
        self.o._request=data;self.o._context()
        self.assertEqual(self.o.context['date'],'2026-11-09');self.assertEqual(self.o.context['open'],101)

    def test_window_filters_preopen_and_after_three_and_reports_gaps(self):
        start=int(datetime.fromisoformat(AT).timestamp())
        bars=[[start+i*60,10,20+i,5,10,1] for i in range(330)]
        extra=[[start-60,10,999,5,10,1],[start+330*60,10,999,5,10,1]]
        r=candle_high({'s':'ok','candles':bars+extra},DAY)
        self.assertEqual(r['high'],349);self.assertEqual(r['minutes'],330)
        self.assertEqual(r['coverage'],'COMPLETE MINUTE BARS')
        self.assertIn('PARTIAL',candle_high({'s':'ok','candles':bars[1:]},DAY)['coverage'])

    def test_conflicting_candles_prevent_complete_coverage(self):
        start=int(datetime.fromisoformat(AT).timestamp());bar=[start,10,20,5,10,1]
        r=candle_high({'s':'ok','candles':[bar,[start,10,25,5,10,1]]},DAY)
        self.assertIn('CONFLICTING',r['coverage'])

if __name__=='__main__':unittest.main()
