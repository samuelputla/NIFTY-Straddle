"""Pure update planner for Delta Based event rows; no broker or Sheet calls."""
import math
from rolling_engine import LOG_HEADERS,CHOICES,LEVELS

def same_cell(a,b):
 if a in ('',None) and b in ('',None):return True
 if str(a)==str(b):return True
 try:
  x,y=float(a),float(b)
  return math.isfinite(x) and math.isfinite(y) and abs(x-y)<1e-9
 except (TypeError,ValueError):return False

def plan_delta_log_updates(title,existing,incoming):
 """Update by Event ID; repeated checkpoints/retries never append duplicates."""
 allowed={f'Delta Based - {choice} Logs':choice for choice in CHOICES}
 if title not in allowed:raise ValueError('Delta log target required')
 if not existing or existing[0]!=LOG_HEADERS:raise ValueError('Unexpected Delta log headers')
 positions={};old={}
 for n,row in enumerate(existing[1:],2):
  if not row or not row[0]:continue
  if row[0] in positions:raise ValueError('Duplicate existing Event ID; review required')
  positions[row[0]]=n;old[row[0]]=row
 next_row=max(2,len(existing)+1);seen=set();updates=[]
 for row in incoming:
  if len(row)!=len(LOG_HEADERS):raise ValueError('Unexpected Delta row width')
  identity=row[0]
  if identity in seen:raise ValueError('Duplicate generated Event ID')
  seen.add(identity)
  expected=f'{row[1]}|Delta Based|{allowed[title]}|{row[4]}|{row[5]}'
  if identity!=expected or row[2]!='Delta Based' or row[3]!=allowed[title] or row[4] not in LEVELS or row[5] not in (1,2,3):raise ValueError('Event identity does not match target')
  if identity in positions:
   prior=old[identity]+['']*(len(LOG_HEADERS)-len(old[identity]))
   if all(same_cell(a,b) for a,b in zip(prior,row)):continue
   number=positions[identity]
  else:
   number=next_row;next_row+=1
  updates.append({'range':f"'{title}'!A{number}:AC{number}",'values':[row]})
 return updates
