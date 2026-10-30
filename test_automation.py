import json,threading,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from automation_dispatch import GitHub,safe_dispatch,IST
from eod_validation import History,DataUnavailable,AuthUnavailable,validate,LEVELS
from market_calendar import session_allowed
DAY='2026-10-30'
def at(clock):return datetime.fromisoformat(DAY+'T'+clock+'+05:30')
class Fixture(BaseHTTPRequestHandler):
 state={}
 def do_GET(self):
  if self.path.startswith('/history'):
   self.send_response(self.state.get('http',200));self.end_headers();self.wfile.write(json.dumps(self.state.get('body',{})).encode());return
  self.state['gets']=self.state.get('gets',0)+1
  if self.state.get('race') and self.state['gets']>=2:self.state['runs']=[run()]
  self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'workflow_runs':self.state.get('runs',[])}).encode())
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.state.setdefault('posts',[]).append(body)
  if not self.state.get('uncertain'):self.state['runs']=[run()]
  self.send_response(204);self.end_headers()
 def log_message(self,*args):pass
def run(status='queued',created=DAY+'T03:37:00Z',conclusion=None):return {'id':111,'status':status,'created_at':created,'conclusion':conclusion,'html_url':'https://github.com/fixture/run/111'}
class TransportTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=cls.server.serve_forever,daemon=True).start();cls.base=f'http://127.0.0.1:{cls.server.server_port}'
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
 def setUp(self):Fixture.state={'runs':[],'posts':[]}
 def dispatch(self,entry=False,clock='09:10:00'):
  return safe_dispatch(GitHub('fixture',self.base),'straddle.yml',{'test_mode':'false','setup_only':'false'},DAY,lambda _:entry,lambda:at(clock))
 def test_success_real_http_and_run_verification(self):
  r=self.dispatch();self.assertEqual(r['status'],'DISPATCH VERIFIED');self.assertEqual(r['run_id'],111);self.assertEqual(Fixture.state['posts'],[{'ref':'main','inputs':{'test_mode':'false','setup_only':'false'}}])
 def test_duplicate_queued_running_failed_and_sheet_guards(self):
  for candidate in [run(),run('in_progress'),run('completed',conclusion='failure'),run(created='2026-10-29T03:00:00Z')]:
   Fixture.state={'runs':[candidate],'posts':[]};self.assertEqual(self.dispatch()['status'],'SKIPPED');self.assertFalse(Fixture.state['posts'])
  Fixture.state={'runs':[],'posts':[]};self.assertEqual(self.dispatch(entry=True)['status'],'SKIPPED');self.assertFalse(Fixture.state['posts'])
 def test_race_recheck_and_late_cutoff(self):
  Fixture.state['race']=True;self.assertEqual(self.dispatch()['status'],'SKIPPED');self.assertFalse(Fixture.state['posts'])
  Fixture.state={'runs':[],'posts':[]};self.assertEqual(self.dispatch(clock='09:25:00')['status'],'SKIPPED');self.assertFalse(Fixture.state['posts'])
 def test_http_204_without_run_is_not_success(self):
  Fixture.state['uncertain']=True
  with patch('automation_dispatch.time.sleep'):r=self.dispatch()
  self.assertEqual(r['status'],'REVIEW');self.assertEqual(len(Fixture.state['posts']),1)
 def test_historical_probe_does_not_block_today_audit(self):
  old=run('completed',conclusion='success');old['display_title']='Daily validation · 2026-10-29';Fixture.state['runs']=[old]
  r=safe_dispatch(GitHub('fixture',self.base),'eod-validation.yml',{},DAY,lambda _:False,lambda:at('16:07:00'),kind='audit')
  self.assertEqual(r['status'],'DISPATCH VERIFIED');self.assertEqual(len(Fixture.state['posts']),1)
 def test_history_cache_and_authentication(self):
  c=[int(at('09:30:00').timestamp()),100,105,95,101,65]
  Fixture.state['body']={'s':'ok','candles':[c]}
  with tempfile.TemporaryDirectory() as root:
   h=History('fixture',root,self.base);self.assertEqual(h.get('CE',DAY),h.get('CE',DAY));self.assertEqual(h.requests,1)
   Fixture.state['body']={'s':'error','code':-16}
   with self.assertRaises(AuthUnavailable):h.get('PE',DAY)
   Fixture.state['body']={'s':'error','code':-99}
   with self.assertRaises(DataUnavailable):h.get('OTHER',DAY)
 def test_history_rejects_duplicate_candles(self):
  c=[int(at('09:30:00').timestamp()),100,105,95,101,65];Fixture.state['body']={'s':'ok','candles':[c,c]}
  with tempfile.TemporaryDirectory() as root:
   with self.assertRaises(DataUnavailable):History('fixture',root,self.base).get('CE',DAY)
class ValidationTests(unittest.TestCase):
 def fixture(self):
  sh=['Date','Expiry','Status','Data Status']+[f'{p}% Profit' for p in LEVELS]+[f'{p}% Cycles' for p in LEVELS]+[f'{p}% Charges' for p in LEVELS]
  summary=[sh,[DAY,'2026-11-23','COMPLETED','Observed paper quotes']+[3450]*9+[3]*9+[450]*9]
  lh=['Date','SL %','Cycle','Strike','Expiry','Entry Time','Entry Spot','Reference Delta','CE Symbol','PE Symbol','CE Entry','PE Entry','CE Exit','PE Exit','CE Exit Time','PE Exit Time','CE Exit Reason','PE Exit Reason','CE Points','PE Points','Net P&L','Charges','Close Time','Close Delta','Delta Changed','Data Status']
  logs=[lh];slots=['09:30:00','11:20:00','13:10:00','15:00:00']
  for p in LEVELS:
   for i in range(3):logs.append([DAY,p,i+1,22750,'2026-11-23',at(slots[i]).isoformat(),22750,'','CE','PE',100,100,90,90,at(slots[i+1]).isoformat(),at(slots[i+1]).isoformat(),'TIME RESET' if i<2 else '15:00 EXIT','TIME RESET' if i<2 else '15:00 EXIT',10,10,1150,150,at(slots[i+1]).isoformat(),'','',''])
  class FakeHistory:
   def get(self,symbol,day):
    if symbol=='NSE:NIFTY50-INDEX':return {at('09:30:00')+timedelta(minutes=i):[0,22750,22755,22745,22750,65] for i in range(331)}
    return {at('09:30:00')+timedelta(minutes=i):[0,100,105,85,90,65] for i in range(331)}
  return summary,logs,FakeHistory()
 def test_complete_three_cycle_reconciliation(self):
  s,l,h=self.fixture();r=validate('Time Based - Monthly',s,l,DAY,h,'2026-11-23');self.assertEqual(r['status'],'PASSED',r);self.assertEqual(r['checked_legs'],54)
 def test_missing_data_not_false_arithmetic_failure(self):
  s,l,h=self.fixture()
  def missing(*args):raise DataUnavailable('fixture missing')
  h.get=missing;r=validate('Time Based - Monthly',s,l,DAY,h,'2026-11-23');self.assertEqual(r['status'],'DATA UNAVAILABLE');self.assertFalse(any(x['level']=='ERROR' and x['check']=='arithmetic' for x in r['findings']))
 def test_corrupt_profit_and_duplicate_cycle_detected(self):
  s,l,h=self.fixture();s[1][4]=3451;l.append(l[1][:]);r=validate('Time Based - Monthly',s,l,DAY,h,'2026-11-23');self.assertEqual(r['status'],'REVIEW');self.assertTrue(any(x['check']=='duplicates' for x in r['findings']));self.assertTrue(any(x['check']=='arithmetic' for x in r['findings']))
 def test_calendar(self):
  self.assertTrue(session_allowed(DAY)[0]);self.assertFalse(session_allowed('2026-10-31')[0]);self.assertFalse(session_allowed('2026-11-10')[0]);self.assertFalse(session_allowed('2027-01-04')[0])
if __name__=='__main__':unittest.main()

