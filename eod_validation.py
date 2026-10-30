"""Report-only validation of nine paper studies. Never edits trade data or orders."""
import argparse,csv,io,json,math,os,re,time
from datetime import datetime,timedelta,time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from market_calendar import session_allowed
IST=ZoneInfo('Asia/Kolkata');LEVELS=(10,15,20,25,30,35,40,45,50)
BOOK='1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI'
INDEX='NSE:NIFTY50-INDEX';QTY=65;COST=150
CHOICES=('Current Week','Next Week','Monthly')
FIXED=('Current Week Expiry','Next Week Expiry','Monthly Expiry')
TABS=list(FIXED)+[f'{f} - {c}' for f in ('Time Based','Delta Based') for c in CHOICES]
class DataUnavailable(RuntimeError):pass
class AuthUnavailable(DataUnavailable):pass
def number(v):
 try:
  if v is None or str(v).strip()=='':return None
  n=float(str(v).replace(',','').replace('₹',''));return n if math.isfinite(n) else None
 except (ValueError,TypeError):return None
def expiry_iso(v):
 text=str(v);return datetime.strptime(text,'%d-%m-%Y').date().isoformat() if re.fullmatch(r'\d{2}-\d{2}-\d{4}',text) else text
def stamp(day,text):
 text=str(text or '')
 if not text:raise DataUnavailable('Missing event time')
 if re.fullmatch(r'\d{2}:\d{2}:\d{2}',text):text=day+'T'+text
 t=datetime.fromisoformat(text.replace('Z','+00:00'))
 if t.tzinfo is None:t=t.replace(tzinfo=IST)
 t=t.astimezone(IST)
 if t.date().isoformat()!=day:raise DataUnavailable('Event date mismatch')
 return t
def records(values):
 if not values:return []
 return [dict(zip(values[0],r)) for r in values[1:] if any(str(x).strip() for x in r)]
def cycles_for(tab,rows,day):
 result=[];fixed=tab in FIXED
 for r in records(rows):
  if str(r.get('Date',''))!=day:continue
  legs={}
  for side in ('CE','PE'):
   legs[side]={'symbol':str(r.get(side+' Symbol','')),'entry':number(r.get(side+' Entry')),'exit':number(r.get(side+(' Exit Price' if fixed else ' Exit'))),'exit_at':r.get(side+' Exit Time',''),'reason':str(r.get(side+' Exit Reason','')),'points':number(r.get(side+(' P&L' if fixed else ' Points')))}
  result.append({'pct':number(r.get('SL %')),'number':1 if fixed else number(r.get('Cycle')),'strike':number(r.get('ATM' if fixed else 'Strike')),'expiry':expiry_iso(r.get('Expiry','')),'entry_at':r.get('Entry Time',''),'spot':number(r.get('NIFTY Spot' if fixed else 'Entry Spot')),'reference':number(r.get('Reference Delta')),'close_at':None if fixed else r.get('Close Time'),'close_delta':number(r.get('Close Delta')),'changed':number(r.get('Delta Changed')),'net':None if fixed else number(r.get('Net P&L')),'charges':COST if fixed else number(r.get('Charges')),'legs':legs,'data_status':str(r.get('Data Status',''))})
 return result
class History:
 def __init__(self,token,out,base='https://api-t1.fyers.in/data'):
  self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True);self.base=base;self.session=requests.Session();self.session.headers['Authorization']='M2DACFCYUO-100:'+token;self.cache={};self.requests=0;self.errors={}
 def get(self,symbol,day):
  key=(symbol,day)
  if key in self.cache:return self.cache[key]
  if key in self.errors:raise DataUnavailable(self.errors[key])
  for attempt in range(3):
   try:
    self.requests+=1;r=self.session.get(self.base+'/history',params={'symbol':symbol,'resolution':'1','date_format':'1','range_from':day,'range_to':day,'cont_flag':'0'},timeout=(3,12))
    if r.status_code==401:raise AuthUnavailable('FYERS authentication needs renewal')
    if r.status_code in (429,500,502,503,504) and attempt<2:time.sleep(2*(attempt+1));continue
    r.raise_for_status();body=r.json()
    if body.get('code') in (-16,'-16'):raise AuthUnavailable('FYERS authentication/access check failed; renew or inspect permissions')
    if body.get('s')!='ok' or not body.get('candles'):raise DataUnavailable('FYERS history unavailable, code '+str(body.get('code')))
    candles={}
    for c in body['candles']:
     at=datetime.fromtimestamp(float(c[0]),IST)
     if at.date().isoformat()!=day or not dt_time(9,15)<=at.time()<=dt_time(15,30):continue
     if at in candles:raise DataUnavailable('Duplicate history timestamp')
     if len(c)<6 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in c[:6]) or not 0<c[3]<=min(c[1],c[4])<=max(c[1],c[4])<=c[2]:raise DataUnavailable('Malformed candle')
     candles[at]=c
    if not candles:raise DataUnavailable('No regular-session candles')
    self.cache[key]=candles;(self.out/(symbol.replace(':','_')+'.json')).write_text(json.dumps(body),encoding='utf-8');time.sleep(.35);return candles
   except AuthUnavailable:raise
   except (requests.RequestException,ValueError,KeyError,DataUnavailable) as error:
    self.errors[key]=type(error).__name__+': history unavailable';raise DataUnavailable(self.errors[key]) from None
  self.errors[key]='Rate limit/service unavailable after bounded retries';raise DataUnavailable(self.errors[key])
def master_expiries(day):
 r=requests.get('https://public.fyers.in/sym_details/NSE_FO.csv',timeout=(3,20));r.raise_for_status();options=set();monthly=set()
 for row in csv.reader(io.StringIO(r.content.decode('utf-8-sig'))):
  if len(row)<17 or row[13]!='NIFTY':continue
  try:expiry=datetime.fromtimestamp(int(row[8]),IST).date().isoformat()
  except (ValueError,TypeError):continue
  if expiry<day:continue
  if row[16] in ('CE','PE'):options.add(expiry)
  elif row[9].endswith('FUT'):monthly.add(expiry)
 listed=sorted(options)
 if len(listed)<2 or not monthly:raise DataUnavailable('Contract master incomplete')
 return dict(zip(CHOICES,[listed[0],listed[1],min(monthly)]))
def validate(tab,summary_values,log_values,day,history,expected_expiry=None):
 findings=[]
 def add(level,check,message):findings.append({'level':level,'check':check,'message':message})
 fixed=tab in FIXED;family='Fixed Entry' if fixed else tab.split(' - ')[0]
 rows=[r for r in records(summary_values) if str(r.get('Date'))==day]
 if len(rows)!=1:return {'strategy':tab,'status':'DATA UNAVAILABLE' if not rows else 'REVIEW','findings':[{'level':'DATA' if not rows else 'ERROR','check':'session','message':'Missing date row' if not rows else 'Duplicate date rows'}]}
 summary=rows[0];status=str(summary.get('Run Status' if fixed else 'Status',''));provenance=str(summary.get('Entry Data Status' if fixed else 'Data Status',''))
 if status!='COMPLETED':add('ERROR','completion','Recorded session is '+status)
 if re.search(r'reconstruct|backfill|user-supplied|historical',provenance,re.I):add('LIMITATION','provenance','Includes historical reconstruction; not an independently observed live session')
 cycles=cycles_for(tab,log_values,day);keys=[(c['pct'],c['number']) for c in cycles]
 if len(set(keys))!=len(keys):add('ERROR','duplicates','Duplicate scenario/cycle IDs')
 expiry=expiry_iso(summary.get('Expiry',''));dte=(datetime.fromisoformat(expiry).date()-datetime.fromisoformat(day).date()).days if re.fullmatch(r'\d{4}-\d{2}-\d{2}',expiry) else None
 if expected_expiry and expiry!=expected_expiry:add('ERROR','expiry',f'Recorded {expiry}, current cross-verified contract master expects {expected_expiry}')
 if dte is None or dte<0:add('ERROR','expiry','Invalid or expired session contract')
 if fixed and number(summary.get('DTE'))!=dte:add('ERROR','DTE','Calendar DTE does not match expiry')
 checked_legs=0
 for pct in LEVELS:
  selected=sorted([c for c in cycles if c['pct']==pct],key=lambda c:c['number'] or 0)
  expected_count=1 if fixed else 3 if family=='Time Based' else len(selected)
  if len(selected)!=expected_count or not 1<=len(selected)<=3:add('ERROR','cycles',f'{pct}%: expected '+str(expected_count)+' cycle(s), recorded '+str(len(selected)))
  if not selected:continue
  if [c['number'] for c in selected]!=list(range(1,len(selected)+1)):add('ERROR','cycles',f'{pct}%: nonconsecutive cycle numbers')
  if not fixed and number(summary.get(f'{pct}% Cycles'))!=len(selected):add('ERROR','cycles',f'{pct}%: summary cycle count mismatch')
  if not fixed and number(summary.get(f'{pct}% Charges'))!=len(selected)*COST:add('ERROR','costs',f'{pct}%: summary cost mismatch')
  expected_net=0;math_complete=True
  for i,cy in enumerate(selected):
   if all(l['entry'] is not None and l['exit'] is not None for l in cy['legs'].values()):
    calculated=round(sum(round(l['entry']-l['exit'],2)*QTY for l in cy['legs'].values())-COST,2);expected_net+=calculated
    if cy['net'] is not None and abs(cy['net']-calculated)>.011:add('ERROR','arithmetic',f'{pct}% cycle{i+1}: cycle net mismatch')
   else:math_complete=False;add('DATA','arithmetic',f'{pct}% cycle{i+1}: unsettled leg values')
   if cy['charges']!=COST:add('ERROR','costs',f'{pct}% cycle{i+1}: expected Rs150 cost')
   if family=='Delta Based' and cy['reference'] is None:add('DATA','delta',f'{pct}% cycle{i+1}: entry delta unavailable')
   if family=='Delta Based' and i+1<len(selected) and all('SL' in l['reason'].upper() or 'STOP' in l['reason'].upper() for l in cy['legs'].values()):add('ERROR','delta','Both legs stopped but another delta cycle was entered; flat positions must not re-enter')
   if cy['expiry']!=expiry:add('ERROR','expiry',f'{pct}% cycle{i+1}: expiry differs from summary')
   try:
    entry_at=stamp(day,cy['entry_at']);entry_minute=entry_at.replace(second=0,microsecond=0)
    boundary=stamp(day,selected[i+1]['entry_at']) if i+1<len(selected) else datetime.fromisoformat(day+'T15:00:00+05:30')
    if i==0 and not dt_time(9,30)<=entry_at.time()<=dt_time(9,35):add('ERROR','entry',f'{pct}%: initial entry outside 09:30–09:35')
    if i and family=='Time Based':
     slot=datetime.fromisoformat(day+'T'+('11:20:00' if i==1 else '13:10:00')+'+05:30')
     if not 0<=(entry_at-slot).total_seconds()<=30:add('ERROR','reset',f'{pct}% cycle{i+1}: outside scheduled reset window')
    if cy['spot'] is None or cy['strike']!=int((cy['spot']+25)//50)*50:add('ERROR','ATM',f'{pct}% cycle{i+1}: strike does not match recorded spot')
    spot_bar=history.get(INDEX,day).get(entry_minute)
    if not spot_bar:add('DATA','spot',f'{pct}% cycle{i+1}: index candle unavailable')
    elif cy['spot'] is not None and not spot_bar[3]-.1<=cy['spot']<=spot_bar[2]+.1:add('REVIEW','spot',f'{pct}% cycle{i+1}: selection spot lies outside entry-minute index range; inspect preselection/receipt time')
    cycle_net=-COST
    for side,leg in cy['legs'].items():
     if leg['entry'] is None or leg['exit'] is None or leg['points'] is None:raise DataUnavailable('Unsettled or missing leg values')
     point=round(leg['entry']-leg['exit'],2);cycle_net+=point*QTY;checked_legs+=1
     if abs(point-leg['points'])>.011:add('ERROR','arithmetic',f'{pct}% cycle{i+1} {side}: point P&L mismatch')
     exit_at=stamp(day,leg['exit_at']);exit_minute=exit_at.replace(second=0,microsecond=0)
     if exit_at<entry_at or exit_at>boundary+timedelta(seconds=15):add('ERROR','time',f'{pct}% cycle{i+1} {side}: invalid exit chronology')
     bars=history.get(leg['symbol'],day);end_minute=boundary.replace(second=0,microsecond=0)
     required=[entry_minute+timedelta(minutes=k) for k in range(int((end_minute-entry_minute).total_seconds()/60)+1)]
     missing=[t for t in required if t not in bars]
     if missing:add('DATA','coverage',f'{pct}% cycle{i+1} {side}: {len(missing)} missing candles')
     entry_bar=bars.get(entry_minute)
     if entry_bar and not entry_bar[3]-.011<=leg['entry']<=entry_bar[2]+.011:add('REVIEW','entry-price',f'{pct}% cycle{i+1} {side}: entry outside minute OHLC range')
     stop=round(leg['entry']*(1+pct/100),2);is_stop='SL' in leg['reason'].upper() or 'STOP' in leg['reason'].upper()
     if is_stop:
      if abs(leg['exit']-stop)>.011:add('ERROR','SL',f'{pct}% cycle{i+1} {side}: threshold fill differs from original leg stop')
      exit_bar=bars.get(exit_minute)
      if exit_bar and exit_bar[2]+.011<stop:add('REVIEW','SL',f'{pct}% cycle{i+1} {side}: stop not reached in recorded crossing minute')
      crossed=next((t for t in sorted(bars) if entry_minute<t<exit_minute and t<end_minute and bars[t][2]>=stop),None)
      if crossed:add('REVIEW','SL',f'{pct}% cycle{i+1} {side}: candle high crossed stop earlier at {crossed.strftime("%H:%M")} than recorded exit minute')
      if exit_minute==entry_minute:add('LIMITATION','SL chronology','Entry and SL are in the same minute; candle ordering cannot prove the crossing occurred after entry')
     else:
      bar=bars.get(exit_minute)
      if not bar:add('DATA','exit-price',f'{pct}% cycle{i+1} {side}: exit candle unavailable')
      elif not bar[3]-.011<=leg['exit']<=bar[2]+.011:add('REVIEW','exit-price',f'{pct}% cycle{i+1} {side}: exit outside minute OHLC range')
      earlier=next((t for t in sorted(bars) if entry_minute<t<exit_minute and bars[t][2]>=stop),None)
      if earlier:add('REVIEW','missed-SL',f'{pct}% cycle{i+1} {side}: minute high crossed the unchanged stop at {earlier.strftime("%H:%M")} despite a non-SL exit')
    if cy['charges']!=COST:add('ERROR','costs',f'{pct}% cycle{i+1}: expected Rs150 cost')
    if cy['net'] is not None and abs(cy['net']-round(cycle_net,2))>.011:add('ERROR','arithmetic',f'{pct}% cycle{i+1}: cycle net mismatch')
    if family=='Delta Based' and i+1<len(selected):
     if cy['reference'] is None or cy['close_delta'] is None or cy['changed'] is None:add('DATA','delta','Missing saved entry/roll delta evidence')
     else:
      change=abs(cy['close_delta']-cy['reference'])
      if change<=.35+1e-12 or abs(cy['changed']-change)>1e-8:add('ERROR','delta','Roll did not satisfy strict >0.35 change from cycle entry reference')
      new_ref=selected[i+1]['reference']
      if new_ref is None or abs(new_ref)>=abs(cy['close_delta']):add('ERROR','delta','Replacement pair does not have smaller absolute net delta')
   except AuthUnavailable:raise
   except (DataUnavailable,ValueError,KeyError,TypeError) as error:add('DATA','cycle',f'{pct}% cycle{i+1}: {str(error)[:140]}')
  actual=number(summary.get(f'{pct}% Profit'))
  if actual is None:add('DATA','arithmetic',f'{pct}%: summary profit unavailable')
  elif math_complete and abs(actual-round(expected_net,2))>.02:add('ERROR','arithmetic',f'{pct}%: summary net does not reconcile with recorded legs and costs')
 if family=='Delta Based':add('LIMITATION','delta','Saved entry/roll deltas checked where present; OHLC history cannot independently reconstruct the original continuous delta path or prove no missed trigger')
 # Deduplicate repeated scenario-level limitations, without dropping distinct checks.
 findings=list({json.dumps(x,sort_keys=True):x for x in findings}.values())
 result='REVIEW' if any(x['level'] in ('ERROR','REVIEW') for x in findings) else 'DATA UNAVAILABLE' if any(x['level']=='DATA' for x in findings) else 'PASSED'
 return {'strategy':tab,'status':result,'expiry':expiry,'checked_legs':checked_legs,'findings':findings}
def write_report(report,out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 lines=[f"# Daily paper strategy validation — {report['date']}",'',f"Result: **{report['status']}**. Report-only: original Sheet values, collectors and orders were not changed.",'','| Strategy | Result | Legs checked | Findings |','|---|---|---:|---:|']
 for r in report['strategies']:lines.append(f"| {r['strategy']} | {r['status']} | {r.get('checked_legs',0)} | {len(r['findings'])} |")
 lines+=['','Checks compare observed prices with historical minute ranges, not exact second-level fills. Threshold fills, costs and zero additional slippage remain paper assumptions. A passed price-range check is not independent proof of an executable fill. Missing data is never treated as zero. No expired-data endpoint is called; quota-limited expired history is not automatically retried.','']
 for r in report['strategies']:
  lines+=['## '+r['strategy']]
  lines += [f"- {x['level']} · {x['check']}: {x['message']}" for x in r['findings']] or ['- All available checks passed.']
 (out/'report.md').write_text('\n'.join(lines),encoding='utf-8')
 if os.getenv('GITHUB_STEP_SUMMARY'):
  with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:f.write('\n'.join(lines))
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--date',default='');parser.add_argument('--out',default='validation-report');args=parser.parse_args();now=datetime.now(IST);day=args.date or now.date().isoformat()
 if day>now.date().isoformat() or (day==now.date().isoformat() and now.time()<dt_time(16,7)):raise RuntimeError('Audit only after 16:07 IST; no unfinished current session audit')
 allowed,reason=session_allowed(day)
 if not allowed:
  if 'outside verified' in reason:raise RuntimeError(reason)
  print('SKIPPED: '+reason);return
 import gspread
 from google.oauth2.service_account import Credentials
 client=gspread.authorize(Credentials.from_service_account_info(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']));client.set_timeout((3,15));book=client.open_by_key(BOOK)
 ranges=[f"'{t}'!A1:{'CE' if t in FIXED else 'AK'}1000" for t in TABS]+[f"'{t} Logs'!A1:{'AE' if t in FIXED else 'AC'}5000" for t in TABS]
 response=book.values_batch_get(ranges,params={'valueRenderOption':'UNFORMATTED_VALUE'});sets=response['valueRanges'];summaries={t:sets[i].get('values',[]) for i,t in enumerate(TABS)};logs={t:sets[i+9].get('values',[]) for i,t in enumerate(TABS)}
 Path(args.out).mkdir(parents=True,exist_ok=True);Path(args.out,'source-sheet-snapshot.json').write_text(json.dumps({'summaries':summaries,'logs':logs}),encoding='utf-8')
 history=History(os.environ['FYERS_ACCESS_TOKEN'],Path(args.out,'history'));results=[];expiry_map={};master_note=''
 try:expiry_map=master_expiries(day)
 except Exception:master_note='Current symbol-master verification unavailable; expiry selection requires review'
 try:
  for i,tab in enumerate(TABS):
   r=validate(tab,summaries[tab],logs[tab],day,history,expiry_map.get(CHOICES[i%3]))
   if master_note:r['findings'].append({'level':'DATA','check':'expiry-master','message':master_note});r['status']='DATA UNAVAILABLE' if r['status']=='PASSED' else r['status']
   results.append(r)
 except AuthUnavailable:
  for tab in TABS:
   if not any(r['strategy']==tab for r in results):results.append({'strategy':tab,'status':'DATA UNAVAILABLE','findings':[{'level':'DATA','check':'authentication','message':'FYERS login/access needs renewal; no credentials printed and no automatic repeated login attempts'}]})
 report={'date':day,'asof':now.isoformat(),'status':'REVIEW' if any(r['status']=='REVIEW' for r in results) else 'DATA UNAVAILABLE' if any(r['status']=='DATA UNAVAILABLE' for r in results) else 'PASSED','strategies':results,'unique_history_requests':history.requests,'expired_endpoint_requests':0,'source':'FYERS one-minute History + saved Sheet records','mode':'report only'}
 write_report(report,args.out);print(json.dumps({k:report[k] for k in ('date','status','unique_history_requests','expired_endpoint_requests')}))
 if len(results)!=9 or any(x['level']=='ERROR' or x['check']=='authentication' for r in results for x in r['findings']):raise SystemExit(1)
if __name__=='__main__':main()

