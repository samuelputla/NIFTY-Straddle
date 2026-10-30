"""Post-session comparison publisher; writes only two dedicated research tabs."""
import argparse,datetime as dt,gzip,io,json,os,time,zipfile
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from comparison_engine import HEADERS,VARIANTS,Quotes,compare_day,regime,finite,prepare,net
from comparison_protocol import START,VERSION,event_day,RBI_SOURCE,RBI_SCOPE,phase_for
from eod_validation import BOOK,TABS,FIXED,LEVELS,cycles_for,records
from measurement_log import EvidenceWriter
IST=ZoneInfo('Asia/Kolkata');REPO='samuelputla/NIFTY-Straddle'
CONTEXT_HEADERS=['Event ID','Date','Version','Regime','Efficiency Ratio','Gap %','Gap Direction','Prior VIX 20-session Average','RBI MPC Day','Event Scope','Event Source','Eligible Baseline Day','Evaluation Phase','Cohort Day','Updated At IST','Coverage Notes']
def check(response):
 if not 200<=response.status_code<300:raise RuntimeError('Research dependency HTTP '+str(response.status_code))
FAMILIES=['Fixed Entry','Time Based','Delta Based'];CHOICES=['Current Week','Next Week','Monthly']
def read_capture(raw,day,short_symbols,wing_keys):
 events=[];end=None;start=None;total=0
 with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
  for line in f:
   total+=len(line)
   if total>250*1024*1024:raise ValueError('Capture inflated-size limit exceeded')
   e=json.loads(line)
   if e.get('k')=='start':start=e
   elif e.get('k')=='end':end=e
   elif e.get('k')=='q' and e.get('s') in short_symbols:events.append(e)
   elif e.get('k')=='chain':
    e['rows']=[r for r in e.get('rows',[]) if (e.get('expiry'),r[1],r[2]) in wing_keys];events.append(e)
 if not start or start.get('date')!=day or start.get('normal') is not True or start.get('version')!=VERSION:raise ValueError('Wrong or test observer capture')
 if not end or end.get('dropped') or end.get('failed'):raise ValueError('Incomplete observer capture')
 return start['source'],events

def download_captures(day,token,short_symbols,wing_keys):
 if not token:return {},['GitHub artifact access unavailable']
 session=requests.Session();session.headers.update(Authorization='Bearer '+token,Accept='application/vnd.github+json');found={};notes=[]
 for workflow in ('straddle.yml','rolling-straddles.yml'):
  r=session.get(f'https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/runs',params={'branch':'main','per_page':30},timeout=(3,15));check(r)
  runs=[x for x in r.json()['workflow_runs'] if dt.datetime.fromisoformat(x['created_at'].replace('Z','+00:00')).astimezone(IST).date().isoformat()==day]
  for run in runs:
   if run['status']!='completed':continue
   r=session.get(f'https://api.github.com/repos/{REPO}/actions/runs/{run["id"]}/artifacts',params={'per_page':100},timeout=(3,15));check(r)
   for a in r.json()['artifacts']:
    if not a['name'].startswith(('fixed-execution-','rolling-paper-state-')) or a.get('expired'):continue
    if a['size_in_bytes']>250*1024*1024:notes.append('Oversize observer artifact');continue
    r=session.get(f'https://api.github.com/repos/{REPO}/actions/artifacts/{a["id"]}/zip',timeout=(5,90));check(r)
    if len(r.content)>250*1024*1024:raise ValueError('Artifact download limit')
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
     for name in z.namelist():
      if not Path(name).name.startswith('comparison_capture_') or not name.endswith('.jsonl.gz'):continue
      info=z.getinfo(name)
      if info.file_size>250*1024*1024:raise ValueError('Capture size limit')
      try:source,events=read_capture(z.read(name),day,short_symbols,wing_keys)
      except (ValueError,OSError) as e:notes.append(str(e));continue
      # Run lists are newest first; never mix two captures for the same collector.
      if source not in found:found[source]=events
 return found,notes

def history(symbol,day,resolution,start=None):
 r=requests.get('https://api-t1.fyers.in/data/history',headers={'Authorization':'M2DACFCYUO-100:'+os.environ['FYERS_ACCESS_TOKEN'].strip()},params={'symbol':symbol,'resolution':resolution,'date_format':'1','range_from':start or day,'range_to':day,'cont_flag':'0'},timeout=(3,15));check(r);data=r.json()
 if data.get('s')!='ok':raise ValueError('FYERS context history unavailable: '+str(data.get('code')))
 return data.get('candles',[])

def context_history(day):
 result={'regime':'Unknown','gap_direction':'Unknown','event_day':event_day(day)};notes=[]
 try:
  candles=history('NSE:NIFTY50-INDEX',day,'1');result['regime'],result['efficiency']=regime(candles,day)
 except Exception as e:notes.append('Intraday regime unavailable: '+type(e).__name__)
 time.sleep(1)
 try:
  rows=history('NSE:NIFTY50-INDEX',day,'D',(dt.date.fromisoformat(day)-dt.timedelta(days=90)).isoformat());prior=sorted((r for r in rows if dt.datetime.fromtimestamp(r[0],IST).date().isoformat()<day),key=lambda r:r[0]);today=[r for r in rows if dt.datetime.fromtimestamp(r[0],IST).date().isoformat()==day]
  if prior and today and prior[-1][4]>0:
   result['gap_pct']=(today[0][1]-prior[-1][4])/prior[-1][4]*100;result['gap_direction']='Gap up' if result['gap_pct']>0 else 'Gap down' if result['gap_pct']<0 else 'Flat'
 except Exception as e:notes.append('Gap context unavailable: '+type(e).__name__)
 time.sleep(1)
 try:
  rows=history('NSE:INDIAVIX-INDEX',day,'D',(dt.date.fromisoformat(day)-dt.timedelta(days=90)).isoformat());prior=sorted((r for r in rows if dt.datetime.fromtimestamp(r[0],IST).date().isoformat()<day),key=lambda r:r[0]);dates=[dt.datetime.fromtimestamp(r[0],IST).date() for r in prior[-20:]]
  if len(prior)>=20 and len(set(dates))==20:result['prior_vix_20']=sum(r[4] for r in prior[-20:])/20
  else:notes.append('Fewer than 20 distinct prior VIX closes')
 except Exception as e:notes.append('VIX context unavailable: '+type(e).__name__)
 return result,notes

def publish(rows,contexts,token):
 from google.auth.crypt import RSASigner
 import base64
 signer=RSASigner.from_service_account_info(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']))
 from comparison_snapshot import compact
 months=sorted({str(r[1])[:7] for r in rows if len(r)>7 and str(r[6])==VERSION})
 session=requests.Session();headers={'Content-Type':'application/json'}
 if token:headers['OAI-Sites-Authorization']='Bearer '+token
 def send(payload):
  payload['sentAt']=dt.datetime.now(IST).isoformat();raw=json.dumps(payload,separators=(',',':')).encode();signed={**headers,'X-Comparison-Signature':base64.b64encode(signer.sign(raw)).decode()}
  r=session.post('https://nifty-straddle-lab.cosmicbay1.chatgpt.site/api/comparisons',data=raw,headers=signed,timeout=(5,45));check(r)
 for month in months:
  payload=compact([r for r in rows if str(r[1]).startswith(month)],month)
  if len(json.dumps(payload).encode())>3800000:raise ValueError('Comparison month snapshot too large; previous snapshot retained')
  send(payload)
 payload={'kind':'index','version':VERSION,'months':months,'start':START,'eligibleDays':sum(str(r[11]).upper()=='TRUE' for r in contexts if len(r)>13 and r[2]==VERSION),'eventScope':RBI_SCOPE,'eventSource':RBI_SOURCE,'updatedAt':dt.datetime.now(IST).isoformat()}
 send(payload)

def main():
 import gspread
 from google.oauth2.service_account import Credentials
 p=argparse.ArgumentParser();p.add_argument('--setup-only',action='store_true');args=p.parse_args();now=dt.datetime.now(IST);day=now.date().isoformat()
 client=gspread.authorize(Credentials.from_service_account_info(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),scopes=['https://www.googleapis.com/auth/spreadsheets']));client.set_timeout((3,15));book=client.open_by_key(BOOK);writer=EvidenceWriter(book)
 outws,_=writer.sheet('Research Comparisons',HEADERS);contextws,prior_context=writer.sheet('Comparison Market Regimes',CONTEXT_HEADERS)
 if args.setup_only:print('Comparison schemas ready; no broker requests or baseline edits');return
 if day<START:print('Comparison collection starts '+START+'; no historical results invented');return
 from market_calendar import session_allowed
 allowed,reason=session_allowed(day)
 if not allowed:print('SKIPPED '+reason);return
 if now.time().replace(tzinfo=None)<dt.time(16,7):raise ValueError('Comparison run is post-session only')
 response=book.values_batch_get([f"'{t} Logs'!A1:{'AE' if t in FIXED else 'AC'}5000" for t in TABS]+[f"'{t}'!A1:CE1000" for t in TABS],params={'valueRenderOption':'UNFORMATTED_VALUE'})['valueRanges']
 cases=[];symbols=set();wing_keys=set();baseline_ok=True
 for i,t in enumerate(TABS):
  family='Fixed Entry' if t in FIXED else t.split(' - ')[0];choice=CHOICES[FIXED.index(t)] if t in FIXED else t.split(' - ')[1];data=response[i].get('values',[])
  if t in FIXED and data and 'Run Type' in data[0]:
   runidx=data[0].index('Run Type');data=[data[0]]+[r for r in data[1:] if len(r)>runidx and r[runidx]=='SCHEDULED PAPER']
  raw=cycles_for(t,data,day);summary=[r for r in records(response[i+9].get('values',[])) if r.get('Date')==day];ready=len(summary)==1 and str(summary[0].get('Run Status' if t in FIXED else 'Status','')).upper()=='COMPLETED'
  entry_vix=summary[0].get('Vix at 09:30 AM' if t in FIXED else 'India VIX') if summary else None
  try:entry_vix=float(entry_vix)
  except (ValueError,TypeError):entry_vix=None
  for pct in LEVELS:
   cycles=[c for c in raw if c['pct']==pct] if ready else []
   try:
    prepared=prepare(day,cycles);expected=float(summary[0][f'{pct}% Profit'])
    if abs(net(prepared)-expected)>.02:raise ValueError('Baseline summary does not reconcile')
    if t not in FIXED and len(prepared)!=int(summary[0][f'{pct}% Cycles']):raise ValueError('Baseline cycle count mismatch')
   except Exception:baseline_ok=False;cases.append((family,choice,pct,[],entry_vix));continue
   cases.append((family,choice,pct,cycles,entry_vix))
   for c in prepared:
    symbols.update(l['symbol'] for l in c['legs'].values())
    for width in (500,1000):wing_keys.update({(c['expiry'],c['strike']+width,'CE'),(c['expiry'],c['strike']-width,'PE')})
 captures,notes=download_captures(day,os.environ.get('GITHUB_TOKEN',''),symbols,wing_keys);context,hnotes=context_history(day);notes+=hnotes
 previous=[r for r in prior_context[1:] if r and len(r)>13 and r[1]<day and r[2]==VERSION and str(r[11]).upper()=='TRUE'];existing=[r for r in prior_context[1:] if r and len(r)>13 and r[1]==day and r[2]==VERSION];cohort=len({r[1] for r in previous})+1 if baseline_ok else None
 phase=phase_for(cohort)
 if existing and existing[0][13]:cohort=int(existing[0][13]);phase=existing[0][12]
 rows=[];chains=[e for e in captures.get('rolling',[]) if e.get('k')=='chain']
 for family,choice,pct,cycles,entry_vix in cases:
  key='fixed_'+choice.replace(' ','_') if family=='Fixed Entry' else 'rolling';events=captures.get(key,[])
  # A response retrieved after entry must never become an entry-time gate.
  entry_vix=None
  if cycles:
   from comparison_engine import ts
   entry_at=min(ts(day,c['entry_at']) for c in cycles);known=[e for e in chains if finite(e.get('vix')) and 0<=entry_at-dt.datetime.fromisoformat(e['t']).timestamp()<=30]
   if known:entry_vix=max(known,key=lambda e:e['t'])['vix']
  r=compare_day(day,family,choice,pct,cycles,Quotes(events),chains,{**context,'entry_vix':entry_vix},phase,os.environ.get('GITHUB_SERVER_URL','https://github.com')+'/'+REPO+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','local'))
  rows.extend(r)
 writer.save('Research Comparisons',HEADERS,rows,update=True)
 c=[VERSION+'|'+day,day,VERSION,context.get('regime','Unknown'),context.get('efficiency',''),context.get('gap_pct',''),context.get('gap_direction','Unknown'),context.get('prior_vix_20',''),context.get('event_day') if context.get('event_day') is not None else '',RBI_SCOPE,RBI_SOURCE,baseline_ok,phase,cohort or '',now.isoformat(),'; '.join(notes)]
 writer.save('Comparison Market Regimes',CONTEXT_HEADERS,[c],update=True)
 Path('comparison_report').mkdir(exist_ok=True);Path('comparison_report/report.json').write_text(json.dumps({'date':day,'version':VERSION,'baselineComplete':baseline_ok,'phase':phase,'captureSources':list(captures),'notes':notes,'rows':rows}),encoding='utf-8')
 publish(outws.get_all_values()[1:],contextws.get_all_values()[1:],os.environ.get('STRADDLE_DASHBOARD_TOKEN',''))
 print(json.dumps({'date':day,'rows':len(rows),'baselineComplete':baseline_ok,'phase':phase,'unavailable':sum(r[7]=='UNAVAILABLE' for r in rows)}))
if __name__=='__main__':main()

