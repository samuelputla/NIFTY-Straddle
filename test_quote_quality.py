"""Regression checks; HTTP fixtures exercise the actual reset worker body."""
import ast,copy,json,threading,time,unittest
from pathlib import Path
from datetime import datetime
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import requests
from quote_quality import IST,trade_timestamp,quote_prices
from rolling_engine import Study

ROOT=Path(__file__).parent
def function(path,name):
 tree=ast.parse((ROOT/path).read_text(encoding='utf-8'))
 return copy.deepcopy(next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name))
def compile_function(node,scope):
 exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'regression','exec'),scope)
 return scope[node.name]

class QualityTests(unittest.TestCase):
 def test_trade_timestamp(self):
  for value in [None,'',0,'bad',1793232000,1793232000000,float('nan')]:self.assertIsNone(trade_timestamp(value))
  stamp=datetime(2026,10,29,9,30,tzinfo=IST)
  self.assertEqual(trade_timestamp(stamp.timestamp()),stamp)
 def test_fixed_exits_use_event_time(self):
  for path in ['today_test.py','next_expiry_straddle.py','monthly_expiry_straddle.py']:
   tree=ast.parse((ROOT/path).read_text(encoding='utf-8'))
   for n in ast.walk(tree):
    if isinstance(n,ast.Assign) and any(isinstance(t,ast.Subscript) and isinstance(t.value,ast.Name) and t.value.id=='scenario' and isinstance(t.slice,ast.Constant) and t.slice.value in ['ce_exit_time','pe_exit_time'] for t in n.targets):
     # handle_sl has event time now_ist(); end-of-day has actual finalization receipt.
     self.assertNotIn('final_ce_time',ast.unparse(n.value));self.assertNotIn('final_pe_time',ast.unparse(n.value))
 def test_outgoing_quote_outside_atm_chain(self):
  scope={'chains':{'expiry':{'at':100,'data':{'optionsChain':[{'ltp':22900},{'symbol':'newCE','option_type':'CE','strike_price':22900,'greeks':{'delta':.5}},{'symbol':'newPE','option_type':'PE','strike_price':22900,'greeks':{'delta':-.5}}]}}},'prices':{'oldPE':(50,99),'newCE':(100,99),'newPE':(101,99)},'options':{'expiry':{(22900,'CE'):'newCE',(22900,'PE'):'newPE'}},'good':__import__('rolling_engine').good}
  pair,gs,qs=compile_function(function('rolling_collector.py','pair_for'),scope)('expiry',100)
  self.assertEqual(qs['oldPE'],50);self.assertEqual(pair['CE']['price'],100)
  pair,gs,qs=scope['pair_for']('expiry',111);self.assertNotIn('oldPE',qs)
 def test_reset_worker_http_success_and_failures(self):
  state={'body':{'s':'ok','d':[{'n':'CE','v':{'lp':99}},{'n':'PE','v':{'lp':101}}]},'status':200}
  class Handler(BaseHTTPRequestHandler):
   def do_POST(self):
    self.rfile.read(int(self.headers.get('Content-Length','0')))
    self.send_response(state['status']);self.end_headers();self.wfile.write(json.dumps(state['body']).encode())
   def log_message(self,*args):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   def call(method,payload):
    response=requests.post(f'http://127.0.0.1:{server.server_port}/quotes',json=payload,timeout=.5);response.raise_for_status();return response.json()
   scope={'key':'reset','needed':['CE','PE'],'missing':['CE','PE'],'call':call,'quote_prices':quote_prices,'now':lambda:datetime(2026,10,29,11,20,10,tzinfo=IST),'lock':threading.RLock(),'prices':{},'time':time,'studies':[],'reset_diagnostics':{}}
   run=compile_function(function('rolling_collector.py','reset_quotes'),scope)
   run();self.assertEqual(scope['prices']['CE'][0],99)
   for status,body in [(429,{}),(200,{'s':'error','code':-16}),(200,{'s':'ok','d':[{'n':'CE','v':{'lp':99}}]})]:
    scope['prices'].clear();state.update(status=status,body=body);run();self.assertFalse(scope['prices']);self.assertEqual(scope['reset_diagnostics']['reset']['readiness'],'REST FALLBACK FAILED')
  finally:server.shutdown();server.server_close()
 def test_engine_deadline_not_bypassed(self):
  for seconds,cycles in [('11:20:30',2),('11:20:31',1)]:
   s=Study('Time Based','Monthly','2026-11-23','2026-10-29')
   pair={'at':1,'spot':22750,'strike':22750,'CE':{'symbol':'CE','price':100,'delta':.5},'PE':{'symbol':'PE','price':100,'delta':-.5}}
   s.advance('2026-10-29T09:30:00+05:30',pair,{}, {},1)
   s.advance('2026-10-29T'+seconds+'+05:30',pair,{'CE':99,'PE':101},{},1)
   self.assertEqual(len(s.scenarios[25].cycles),cycles)
if __name__=='__main__':unittest.main()

