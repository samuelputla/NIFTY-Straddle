"""Bounded retries for reads and deterministic Sheet writes; no append retries."""
import random,time
from gspread.http_client import HTTPClient
from gspread.exceptions import APIError

class ResilientHTTPClient(HTTPClient):
 def request(self,method,endpoint,**kwargs):
  safe=method.lower()=='get' or (method.lower()=='post' and endpoint.endswith('/values:batchUpdate'))
  for attempt in range(7):
   try:return super().request(method,endpoint,**kwargs)
   except APIError as error:
    if not safe or error.response.status_code not in (429,500,502,503,504) or attempt==6:raise
    time.sleep(min(32,2**attempt)+random.random())

class RollingSheetStore:
 """Single-writer cached ranges. Retry writes at identical cells after uncertain errors."""
 def __init__(self,book,schemas):
  self.book=book;self.schemas=schemas
  ranges=["'"+n.replace("'","''")+"'!A1:"+col(len(h)) for n,h in schemas.items()]
  result=book.values_batch_get(ranges)
  values=result.get('valueRanges',[])
  if len(values)!=len(schemas):raise RuntimeError('Incomplete startup Sheet batch')
  self.rows={n:v.get('values',[]) for n,v in zip(schemas,values)}
  for n,h in schemas.items():
   if not self.rows[n]:self.rows[n]=[h];book.values_batch_update({'valueInputOption':'RAW','data':[{'range':quoted(n)+'!A1','values':[h]}]})
   if self.rows[n][0]!=h:raise RuntimeError('Unexpected schema: '+n)
   if n.endswith(' Logs'):
    ids=[r[0] for r in self.rows[n][1:] if r and r[0]]
    if len(ids)!=len(set(ids)):raise RuntimeError('Duplicate existing event IDs: '+n)
 def check_day(self,day):
  for n,rows in self.rows.items():
   if not n.endswith(' Logs') and any(r and r[0]==day for r in rows[1:]):
    raise RuntimeError('Existing challenger session; duplicate refused')
 def checkpoint(self,summaries,logsets):
  updates=[]
  for n,incoming in [(n,[r]) for n,r in summaries]+logsets:
   rows=self.rows[n];positions={r[0]:i for i,r in enumerate(rows) if r and r[0]}
   seen=set()
   for row in incoming:
    if len(row)!=len(self.schemas[n]) or not row[0] or row[0] in seen:raise RuntimeError('Invalid generated row: '+n)
    seen.add(row[0]);i=positions.get(row[0])
    if i is None:i=len(rows);rows.append(list(row));positions[row[0]]=i
    else:rows[i]=list(row)
    updates.append({'range':quoted(n)+'!A'+str(i+1),'values':[row]})
  # Cache reserves stable row locations before sending: uncertain responses cannot append duplicates.
  self.book.values_batch_update({'valueInputOption':'RAW','data':updates})
 def snapshot(self,n):return self.rows[n]

def quoted(n):return "'"+n.replace("'","''")+"'"
def col(n):
 out=''
 while n:n,r=divmod(n-1,26);out=chr(65+r)+out
 return out

