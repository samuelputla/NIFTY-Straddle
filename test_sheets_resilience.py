import unittest,requests
from sheets_resilience import RollingSheetStore,ResilientHTTPClient
from unittest.mock import patch
class Book:
 def __init__(self):self.reads=0;self.calls=[];self.fail=False
 def values_batch_get(self,ranges):
  self.reads+=1;return {'valueRanges':[{'values':[['Date','Value'],['old',1]]},{'values':[['ID','Value']]}]}
 def values_batch_update(self,body):
  self.calls.append(body)
  if self.fail:self.fail=False;raise TimeoutError('ambiguous response')
class Tests(unittest.TestCase):
 def test_cache_and_uncertain_write(self):
  b=Book();s=RollingSheetStore(b,{'Summary':['Date','Value'],'Study Logs':['ID','Value']})
  b.fail=True
  with self.assertRaises(TimeoutError):s.checkpoint([('Summary',['today',3])],[('Study Logs',[['event',1]])])
  first=b.calls[-1];s.checkpoint([('Summary',['today',3])],[('Study Logs',[['event',1]])])
  self.assertEqual(first,b.calls[-1]);self.assertEqual(len(s.snapshot('Study Logs')),2)
  s.checkpoint([('Summary',['today',4])],[('Study Logs',[['event',2]])])
  self.assertEqual(b.reads,1);self.assertEqual(s.snapshot('Study Logs')[-1],['event',2])
  with self.assertRaises(RuntimeError):s.check_day('today')
 def test_retry_rules_over_http(self):
  import os
  base=os.environ.get('QUOTA_TEST_URL')
  if not base:self.skipTest('Set QUOTA_TEST_URL to Postman simulation')
  session=requests.Session();c=ResilientHTTPClient(None,session=session)
  with patch('sheets_resilience.time.sleep') as sleep:
   response=c.request('get',base+'/reads');self.assertEqual(response.status_code,200);self.assertEqual(sleep.call_count,2)
   response=c.request('post',base+'/values:batchUpdate',json={'data':[{'range':'A2','values':[['event']]}]});self.assertEqual(response.status_code,200)
   from gspread.exceptions import APIError
   with self.assertRaises(APIError):c.request('post',base+'/values:append',json={})
  state=session.get(base+'/fixture/state').json()
  self.assertEqual(state['reads'],3);self.assertEqual(state['writes'],2);self.assertEqual(state['appends'],1)
if __name__=='__main__':unittest.main()

