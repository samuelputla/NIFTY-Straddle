"""Optional bounded observer journal. No network, orders or shared strategy state."""
import gzip,json,queue,threading,time
from datetime import datetime
from pathlib import Path
VERSION='comparison-v1'
class Capture:
 def __init__(self,day,source,enabled=True):
  self.day,self.source,self.enabled=day,source,enabled;self.dropped=0;self.failed='';self.count=0;self.q=queue.Queue(20000);self.thread=None
  if enabled:
   try:
    self.path=Path('comparison_capture_'+source+'.jsonl.gz');self.thread=threading.Thread(target=self._write,daemon=True);self.thread.start();self.put({'k':'start','date':day,'source':source,'version':VERSION,'normal':True})
   except Exception as e:self.failed=type(e).__name__;self.enabled=False;self.thread=None
 def put(self,row):
  if not self.enabled:return
  try:self.q.put_nowait(row)
  except queue.Full:self.dropped+=1
  except Exception as e:self.failed=type(e).__name__;self.enabled=False
 def quote(self,at,symbol,price):
  if not self.enabled:return
  try:
   if '09:29:00'<=at[11:19]<='15:00:30':self.put({'k':'q','t':at,'s':symbol,'p':price})
  except Exception as e:self.failed=type(e).__name__;self.enabled=False
 def chain(self,at,expiry,data):
  if not self.enabled:return
  try:
   if not '09:29:00'<=at[11:19]<'15:00:00':return
   rows=[[x.get('symbol'),x.get('strike_price'),x.get('option_type'),x.get('bid'),x.get('ask')] for x in data.get('optionsChain',[]) if x.get('option_type') in ('CE','PE')]
   self.put({'k':'chain','t':at,'expiry':expiry,'rows':rows,'vix':(data.get('indiavixData') or {}).get('ltp')})
  except Exception as e:self.failed=type(e).__name__;self.enabled=False
 def _write(self):
  try:
   with gzip.open(self.path,'wt',encoding='utf-8') as f:
    while True:
     row=self.q.get()
     if row is None:break
     f.write(json.dumps(row,separators=(',',':'))+'\n');self.count+=1
     if self.count%1000==0:f.flush()
     if self.path.stat().st_size>25*1024*1024:raise RuntimeError('Observer storage limit reached')
  except Exception as e:self.failed=type(e).__name__;self.enabled=False
 def close(self):
  if not self.thread:return
  self.put({'k':'end','date':self.day,'source':self.source,'dropped':self.dropped,'failed':self.failed})
  try:self.q.put(None,timeout=1);self.thread.join(timeout=5)
  except queue.Full:self.failed='Undrained queue'
  if self.failed or self.dropped or self.thread.is_alive():print('Comparison observer incomplete; core results unchanged',self.failed,self.dropped)

