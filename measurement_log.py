"""Additive paper evidence only: no pricing changes or broker calls."""
import json,math,threading
from pathlib import Path
from datetime import datetime
DELTA_HEADERS=['Event ID','Date','Expiry Choice','SL %','Cycle','Strike','Expiry','Entry Time','Reference Delta','Last Sample Time','CE Delta (long)','PE Delta (long)','Net Delta (short pair)','Absolute Change','Min Net Delta','Max Net Delta','Max Absolute Change','Samples','Max Sample Gap Seconds','First Threshold Cross Time','Threshold Cross Net Delta','Threshold Cross Change','Cycle Close Time','Close Delta','Roll Recorded','Coverage']
EXEC_HEADERS=['Event ID','Date','Family','Expiry Choice','SL %','Cycle','Symbol','Trigger Time','Stop Threshold','Observed Crossing LTP','Assumed Paper Fill','Adverse Difference Points','Adverse Difference INR','Bid','Ask','Evidence']
def finite(x):return isinstance(x,(int,float)) and math.isfinite(x)
def delta_rows(studies):
 out=[]
 for s in studies:
  if s.family!='Delta Based':continue
  for sc in s.scenarios.values():
   for cy in sc.cycles:
    m=cy.measurement
    out.append([f'{s.day}|{s.choice}|{sc.pct}|{cy.number}',s.day,s.choice,sc.pct,cy.number,cy.strike,s.expiry,cy.entry_at,cy.reference if cy.reference is not None else '',m.get('at',''),m.get('ce',''),m.get('pe',''),m.get('net',''),m.get('change',''),m.get('min',''),m.get('max',''),m.get('max_change',''),m.get('count',0),m.get('gap',0),m.get('cross_at',''),m.get('cross_net',''),m.get('cross_change',''),cy.close_at,cy.close_delta if cy.close_delta is not None else '',cy.number<len(sc.cycles),'Sampled FYERS snapshots; not continuous tick proof' if m else 'No saved Greek observation'])
 return out
def execution_rows(studies):
 out=[]
 for s in studies:
  for sc in s.scenarios.values():
   for cy in sc.cycles:
    for side,l in cy.legs.items():
     if l.observed_stop is None:continue
     out.append(execution_row(s.day,s.family,s.choice,sc.pct,cy.number,l.symbol,l.exit_at,l.stop,l.observed_stop,l.exit))
 return out
def execution_row(day,family,choice,pct,cycle,symbol,at,threshold,observed,fill,bid='',ask=''):
 return [f'{day}|{family}|{choice}|{pct}|{cycle}|{symbol}',day,family,choice,pct,cycle,symbol,at,threshold,observed,fill,round(observed-threshold,4),round((observed-threshold)*65,2),bid,ask,'Observed crossing LTP; not an executable fill; bid/ask unavailable' if bid=='' or ask=='' else 'Observed crossing LTP; bid/ask snapshot only']
class EvidenceWriter:
 def __init__(self,book):self.book=book;self.lock=threading.Lock()
 def sheet(self,title,headers):
  existing={w.title:w for w in self.book.worksheets()};ws=existing.get(title)
  if ws is None:
   # Concurrent collectors may create the same additive tab: re-read on conflict.
   try:ws=self.book.add_worksheet(title,rows=5000,cols=len(headers))
   except Exception:
    ws=self.book.worksheet(title)
  rows=ws.get_all_values()
  if not any(any(str(v).strip() for v in row) for row in rows):ws.update(range_name='A1',values=[headers],value_input_option='RAW');rows=[headers]
  if rows[0]!=headers:raise RuntimeError('Unexpected measurement schema: '+title)
  return ws,rows
 def save(self,title,headers,rows,update=False):
  if not rows:return
  with self.lock:
   ws,prior=self.sheet(title,headers);positions={r[0]:i for i,r in enumerate(prior[1:],2) if r and r[0]};updates=[];new=[]
   for row in rows:
    if row[0] in positions:
     if update:updates.append({'range':'A'+str(positions[row[0]]),'values':[row]})
    else:new.append(row)
   if new:ws.append_rows(new,value_input_option='RAW')
   if updates:ws.batch_update(updates,value_input_option='RAW')


