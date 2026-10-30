"""Isolated comparisons anchored to saved baseline cycles. No orders or baseline writes."""
from datetime import datetime,date,timedelta
import bisect,math
VERSION='comparison-v1';START='2026-11-02';QTY=65;BASE_COST=150
VARIANTS=('BASELINE','EXIT_1330','EXIT_1430','TARGET_40','TARGET_50','WINGS_500','WINGS_1000','FILTER_VIX','FILTER_GAP','FILTER_EVENT')
HEADERS=['Event ID','Date','Family','Expiry Choice','SL %','Variant','Version','Status','Baseline Net','Variant Net','Net Difference','Baseline Costs','Variant Costs','Net at 2x Cost','Regime','Gap Direction','DTE','Gate Decision','Evaluation Phase','Baseline Cycles','Initial Max Expiry Loss','Notes','Run URL']
def finite(x):return isinstance(x,(int,float)) and math.isfinite(x)
def ts(day,text):
 if not text:raise ValueError('Missing event timestamp')
 if len(text)==8:text=day+'T'+text+'+05:30'
 t=datetime.fromisoformat(text.replace('Z','+00:00'))
 if t.tzinfo is None:t=t.replace(tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Kolkata'))
 if t.date().isoformat()!=day:raise ValueError('Event date mismatch')
 return t.timestamp()
def net(cycles):return round(sum(round(l['entry']-l['exit'],2)*QTY for c in cycles for l in c['legs'].values())-len(cycles)*BASE_COST,2)
class Quotes:
 def __init__(self,events):
  self.by={}
  for e in events:
   if e.get('k')=='q' and finite(e.get('p')) and e['p']>0:self.by.setdefault(e['s'],[]).append((datetime.fromisoformat(e['t']).timestamp(),e['p']))
  for s,rows in self.by.items():self.by[s]=sorted(set(rows))
 def after(self,symbol,at,max_age=10):
  rows=self.by.get(symbol,[]);i=bisect.bisect_left(rows,(at,-math.inf))
  if i==len(rows) or rows[i][0]-at>max_age:raise ValueError('Missing exit quote within 10 seconds')
  return rows[i][1]
 def path(self,cy,end):
  start=cy['start']
  for l in cy['legs'].values():
   until=min(end,l['time']) if 'SL' in l['reason'].upper() or 'STOP' in l['reason'].upper() else end
   stamps=[start]+[t for t,p in self.by.get(l['symbol'],[]) if start<t<until]+[until]
   if any(b-a>10 for a,b in zip(stamps,stamps[1:])):return False
  return True

def prepare(day,cycles):
 out=[]
 for c in sorted(cycles,key=lambda c:ts(day,c['entry_at'])):
  cy={**c,'start':ts(day,c['entry_at']),'legs':{}}
  for side,l in c['legs'].items():
   if not all(finite(l.get(k)) and l[k]>0 for k in ('entry','exit')):raise ValueError('Missing baseline fill')
   cy['legs'][side]={**l,'time':ts(day,l['exit_at'])}
  cy['end']=ts(day,c['close_at']) if c.get('close_at') else max(l['time'] for l in cy['legs'].values())
  if cy['end']<cy['start']:raise ValueError('Invalid baseline cycle chronology')
  out.append(cy)
 if not out:raise ValueError('Missing baseline cycles')
 if len(out)>3 or not '09:30:00'<=datetime.fromtimestamp(out[0]['start'],__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')<='09:35:00':raise ValueError('Invalid initial baseline entry window or cycle limit')
 if any(a['end']>b['start'] for a,b in zip(out,out[1:])):raise ValueError('Overlapping baseline cycles')
 return out

def early(cycles,quotes,deadline):
 profit=0;count=0
 for c in cycles:
  if c['start']>=deadline:break
  count+=1
  for l in c['legs'].values():
   price=l['exit'] if c['end']<=deadline or l['time']<=deadline else quotes.after(l['symbol'],deadline)
   profit+=round(l['entry']-price,2)*QTY
 return round(profit-count*BASE_COST,2),count*BASE_COST

def target(cycles,quotes,fraction,family):
 total=0;count=0
 for c in cycles:
  if not quotes.path(c,c['end']):raise ValueError('Incomplete target path: quote gap greater than 10 seconds')
  count+=1;last={l['symbol']:(c['start'],l['entry']) for l in c['legs'].values()}
  points=sum(round(l['entry']-l['exit'],2) for l in c['legs'].values());hit=False
  events=sorted((t,s,p) for s in last for t,p in quotes.by.get(s,[]) if c['start']<=t<=c['end'])
  for at,s,p in events:
   last[s]=(at,p);marks=[]
   for l in c['legs'].values():
    if l['time']<=at:marks.append(l['exit'])
    elif at-last[l['symbol']][0]<=10:marks.append(last[l['symbol']][1])
    else:break
   if len(marks)!=2:continue
   gross=sum(l['entry']-price for l,price in zip(c['legs'].values(),marks))
   if gross+1e-9>=fraction*sum(l['entry'] for l in c['legs'].values()):points=gross;hit=True;break
  total+=points*QTY
  # Time Based may enter at its next fixed reset; a target-flat Delta study cannot re-enter.
  if hit and family!='Time Based':break
 return round(total-count*BASE_COST,2),count*BASE_COST

def wing_snapshot(chains,expiry,strike,width,at):
 candidates=[e for e in chains if e.get('expiry')==expiry and 0<=at-datetime.fromisoformat(e['t']).timestamp()<=30]
 if not candidates:raise ValueError('Missing pre-event wing snapshot within 30 seconds')
 e=max(candidates,key=lambda x:x['t']);legs=[]
 for side,k in [('CE',strike+width),('PE',strike-width)]:
  rows=[r for r in e['rows'] if r[1]==k and r[2]==side]
  if len(rows)!=1 or not isinstance(rows[0][0],str) or not rows[0][0] or not all(finite(x) and x>0 for x in rows[0][3:5]) or rows[0][4]<rows[0][3]:raise ValueError('Invalid or missing wing bid/ask')
  legs.append(rows[0])
 return legs

def hedged(cycles,chains,width):
 wing_profit=0;first_risk=None
 for c in cycles:
  a=wing_snapshot(chains,c['expiry'],c['strike'],width,c['start']);b=wing_snapshot(chains,c['expiry'],c['strike'],width,c['end'])
  if [l[0] for l in a]!=[l[0] for l in b]:raise ValueError('Wing symbols differ across cycle')
  wing_profit+=sum(y[3]-x[4] for x,y in zip(a,b))*QTY
  if first_risk is None:first_risk=round((width-sum(l['entry'] for l in c['legs'].values())+sum(x[4] for x in a))*QTY,2)
 if first_risk is not None and first_risk<0:raise ValueError('Inconsistent initial wing credit; static loss bound invalid')
 costs=len(cycles)*BASE_COST*2
 return round(net(cycles)+wing_profit-len(cycles)*BASE_COST,2),costs,first_risk

def regime(candles,day):
 rows={datetime.fromtimestamp(r[0],__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).strftime('%H:%M'):r for r in candles if datetime.fromtimestamp(r[0],__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).date().isoformat()==day}
 times=[(datetime(2000,1,1,9,30)+timedelta(minutes=i)).strftime('%H:%M') for i in range(330)]
 if any(t not in rows for t in times):return 'Unknown',None
 path=[rows[times[0]][1]]+[rows[t][4] for t in times]
 travel=sum(abs(b-a) for a,b in zip(path,path[1:]));ratio=abs(path[-1]-path[0])/travel if travel else 0
 label=('Trending up' if path[-1]>path[0] else 'Trending down') if ratio>=.35 else 'Range-bound' if ratio<=.20 else 'Mixed'
 return label,ratio

def gate(variant,context):
 if variant=='FILTER_GAP':value=context.get('gap_pct');return None if not finite(value) else abs(value)<=.75
 if variant=='FILTER_VIX':v,m=context.get('entry_vix'),context.get('prior_vix_20');return None if not finite(v) or not finite(m) or m<=0 else v<=1.2*m
 if variant=='FILTER_EVENT':v=context.get('event_day');return None if v not in (True,False) else not v
 return True

def compare_day(day,family,choice,pct,raw_cycles,quotes,chains,context,phase='CALIBRATION',url=''):
 try:cycles=prepare(day,raw_cycles);baseline=net(cycles);cost=len(cycles)*BASE_COST
 except (ValueError,KeyError,TypeError):cycles=[];baseline=None;cost=None
 expiry=cycles[0]['expiry'] if cycles else '';dte=(date.fromisoformat(expiry)-date.fromisoformat(day)).days if expiry else ''
 out=[]
 for variant in VARIANTS:
  value=None;fees=None;risk='';status='COMPLETE';decision='';note='Sampled paper comparison; baseline fills unchanged'
  if baseline is None:status='UNAVAILABLE';note='Baseline incomplete'
  else:
   try:
    if variant=='BASELINE':value,fees=baseline,cost
    elif variant.startswith('EXIT_'):value,fees=early(cycles,quotes,ts(day,variant[5:7]+':'+variant[7:9]+':00'))
    elif variant.startswith('TARGET_'):value,fees=target(cycles,quotes,int(variant.split('_')[1])/100,family);note='Sampled target path (<=10s gaps); stop priority; Time resets continue; target-flat Delta stops for day'
    elif variant.startswith('WINGS_'):value,fees,risk=hedged(cycles,chains,int(variant.split('_')[1]));status='INDICATIVE';note='Baseline short fills plus pre-event wing ask entry/bid exit <=30s; size unverified; not broker margin; initial static expiry loss only, not rolled daily loss limit'
    else:
     passed=gate(variant,context)
     if passed is None:raise ValueError('Entry filter input unavailable or event calendar not verified')
     decision='TRADE' if passed else 'SKIP';value,fees=(baseline,cost) if passed else (0,0);status='COMPLETE' if passed else 'SKIPPED'
   except (ValueError,KeyError,TypeError) as e:status='UNAVAILABLE';note=str(e);value=None;fees=None
  diff=round(value-baseline,2) if value is not None and baseline is not None else '';stress=round(value-fees,2) if value is not None and fees is not None else ''
  out.append([f'{VERSION}|{day}|{family}|{choice}|{pct}|{variant}',day,family,choice,pct,variant,VERSION,status,baseline if baseline is not None else '',value if value is not None else '',diff,cost if cost is not None else '',fees if fees is not None else '',stress,context.get('regime','Unknown'),context.get('gap_direction','Unknown'),dte,decision,phase,len(cycles),risk,note,url])
 return out

