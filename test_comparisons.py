import unittest,datetime as dt
from pathlib import Path
from comparison_engine import *
from comparison_snapshot import compact
D='2026-11-02'
def at(t):return D+'T'+t+'+05:30'
def cy(start='09:30:00',end='15:00:00',number=1):return dict(pct=25,number=number,strike=23000,expiry='2026-11-03',entry_at=at(start),close_at=at(end),legs={s:dict(symbol=s,entry=100,exit=50,exit_at=at(end),reason='15:00 EXIT') for s in ('CE','PE')})
def quote(t,ce,pe):return [dict(k='q',t=at(t),s=s,p=v) for s,v in [('CE',ce),('PE',pe)]]
class ComparisonTests(unittest.TestCase):
 def test_stop_callback_timestamp_drift_and_target_evidence(self):
  c=cy('09:30:00','09:30:20');c['legs']['CE'].update(exit=125,exit_at=at('09:30:10.000500'),reason='STOP LOSS');c['legs']['PE']['entry']=400;c['legs']['PE']['exit']=100
  q=Quotes(quote('09:30:00',100,400)+quote('09:30:10',150,100)+quote('09:30:20',50,100));trace=[]
  value,cost=target(prepare(D,[c]),q,.5,'Fixed Entry',trace);self.assertEqual(value,17725);self.assertTrue(trace[0]['hit']);self.assertEqual(trace[0]['stopped_fills']['CE'],125)
 def test_research_retry_and_month_read(self):
  from comparison_runner import save_research,month_rows
  class Sheet:
   row_count=100000
   def __init__(self):self.rows=[HEADERS]
   def get(self,r,**kw):
    import re
    a,b=map(int,re.findall(r'\d+',r));rows=self.rows[a-1:b];return [[x[0]] for x in rows] if ':' in r and r.split(':')[1].startswith('A') else rows
   def append_rows(self,rows,**kw):self.rows.extend(rows)
   def batch_update(self,updates,**kw):
    for u in updates:self.rows[int(u['range'][1:])-1]=u['values'][0]
  ws=Sheet();rows=compare_day(D,'Fixed Entry','Current Week',25,[],Quotes([]),[],{});save_research(ws,rows);save_research(ws,rows);self.assertEqual(len(ws.rows),11);self.assertEqual(len(month_rows(ws,'2026-11')),10)
 def test_observer_journal_and_incomplete_capture(self):
  import tempfile,os,gzip,json
  from comparison_capture import Capture
  from comparison_runner import read_capture
  old=os.getcwd()
  with tempfile.TemporaryDirectory(dir=old) as temp:
   try:
    os.chdir(temp);c=Capture(D,'fixed_Current_Week');c.quote(at('09:30:00'),'CE',100);c.close();raw=Path(c.path).read_bytes();source,events=read_capture(raw,D,{'CE'},set());self.assertEqual(source,'fixed_Current_Week');self.assertEqual(len(events),1)
    c=Capture(D,'broken');c.dropped=1;c.close()
    with self.assertRaises(ValueError):read_capture(Path(c.path).read_bytes(),D,{'CE'},set())
    c=Capture(D,'observer_error');c.chain(at('09:30:00'),'2026-11-03',None);self.assertFalse(c.enabled);c.close()
   finally:os.chdir(old)
 def test_fixed_log_clock_only_and_late_entry(self):
  c=cy();c['entry_at']='09:30:02';c['legs']['CE']['exit_at']='15:00:00';self.assertEqual(len(prepare(D,[c])),1)
  c['entry_at']='10:00:00'
  with self.assertRaises(ValueError):prepare(D,[c])
 def test_cohort_freeze_boundaries(self):
  from comparison_protocol import phase_for,event_day
  self.assertEqual(phase_for(60),'CALIBRATION');self.assertEqual(phase_for(61),'HOLDOUT');self.assertEqual(phase_for(90),'HOLDOUT');self.assertEqual(phase_for(91),'POST_HOLDOUT');self.assertTrue(event_day('2026-12-04'));self.assertFalse(event_day('2026-11-02'));self.assertIsNone(event_day('2027-04-01'))
 def test_early_exit_uses_stopped_fill_and_separate_deadlines(self):
  c=cy();c['legs']['CE'].update(exit=125,exit_at=at('10:00:00'),reason='STOP LOSS')
  q=Quotes(quote('13:30:02',180,40)+quote('14:30:01',190,30));cs=prepare(D,[c])
  self.assertEqual(early(cs,q,ts(D,'13:30:00')),(2125,150));self.assertEqual(early(cs,q,ts(D,'14:30:00')),(2775,150))
  self.assertEqual(c['legs']['CE']['exit'],125)
 def test_missing_exit_is_unavailable_not_zero(self):
  out=compare_day(D,'Fixed Entry','Current Week',25,[cy()],Quotes([]),[],{})
  self.assertEqual(out[1][7],'UNAVAILABLE');self.assertEqual(out[1][9],'');self.assertEqual(out[0][9],6350)
 def test_targets_same_tick_stop_priority_and_delta_flat(self):
  c=cy('09:30:00','09:30:20');q=Quotes(quote('09:30:00',100,100)+quote('09:30:10',50,60)+quote('09:30:20',50,50))
  self.assertEqual(target(prepare(D,[c]),q,.4,'Fixed Entry'),(5700,150))
  second=cy('09:31:00','09:31:10',2);q2=Quotes(quote('09:30:00',100,100)+quote('09:30:10',50,60)+quote('09:30:20',50,50)+quote('09:31:00',100,100)+quote('09:31:10',50,50))
  self.assertEqual(target(prepare(D,[c,second]),q2,.4,'Delta Based'),(5700,150));self.assertEqual(target(prepare(D,[c,second]),q2,.4,'Time Based'),(12050,300))
  c['legs']['CE'].update(exit=125,exit_at=at('09:30:10'),reason='STOP LOSS')
  val,_=target(prepare(D,[c]),Quotes(quote('09:30:00',100,100)+quote('09:30:10',50,60)+quote('09:30:20',50,50)),.4,'Fixed Entry');self.assertEqual(val,1475)
 def test_target_rejects_path_gaps(self):
  c=prepare(D,[cy('09:30:00','09:31:00')]);q=Quotes(quote('09:30:00',100,100)+quote('09:31:00',20,20))
  with self.assertRaises(ValueError):target(c,q,.4,'Fixed Entry')
 def test_wings_no_future_quote_both_widths_and_costs(self):
  chains=[]
  for t,b,a in [('09:29:50',9,10),('14:59:50',1,2)]:
   chains.append(dict(k='chain',t=at(t),expiry='2026-11-03',rows=[[s+str(w),23000+(w if s=='CE' else -w),s,b,a] for s in ('CE','PE') for w in (500,1000)]))
  for w in (500,1000):
   n,fees,risk=hedged(prepare(D,[cy()]),chains,w);self.assertEqual(n,5030);self.assertEqual(fees,300);self.assertEqual(risk,(w-180)*65)
  chains[0]['t']=at('09:30:01')
  with self.assertRaises(ValueError):hedged(prepare(D,[cy()]),chains,500)
 def test_gate_boundaries_missing_event_and_skipped_economic_return(self):
  self.assertTrue(gate('FILTER_GAP',{'gap_pct':-.75}));self.assertFalse(gate('FILTER_GAP',{'gap_pct':.751}));self.assertTrue(gate('FILTER_VIX',{'entry_vix':18,'prior_vix_20':15}));self.assertIsNone(gate('FILTER_EVENT',{}))
  r=compare_day(D,'Fixed Entry','Monthly',25,[cy()],Quotes([]),[],{'gap_pct':1})[8];self.assertEqual(r[7],'SKIPPED');self.assertEqual(r[9],0);self.assertEqual(r[12],0);self.assertEqual(r[10],-6350)
 def test_regime_requires_complete_minutes_and_is_descriptive(self):
  rows=[];start=dt.datetime.fromisoformat(at('09:30:00'))
  for i in range(330):rows.append([int((start+dt.timedelta(minutes=i)).timestamp()),100+i,101+i,99+i,101+i,1])
  self.assertEqual(regime(rows,D)[0],'Trending up');self.assertEqual(regime(rows[:-1],D)[0],'Unknown')
 def test_all_nine_scenarios_and_snapshot_dictionary(self):
  for f in ['Fixed Entry','Time Based','Delta Based']:
   for choice in ['Current Week','Next Week','Monthly']:
    r=compare_day(D,f,choice,50,[cy()],Quotes([]),[],{});self.assertEqual(len(r),10);self.assertEqual(len({x[0] for x in r}),10)
    s=compact(r,'2026-11');self.assertEqual(len(s['values']),10);self.assertTrue(all(len(x)==len(s['columns']) for x in s['values']))
if __name__=='__main__':unittest.main()

