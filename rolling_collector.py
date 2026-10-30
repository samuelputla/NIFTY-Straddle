"""Six isolated paper challengers. No order placement endpoints or broker orders."""
import csv,io,json,os,threading,time,urllib.request
from pathlib import Path
from datetime import datetime,time as dt_time
from zoneinfo import ZoneInfo
from rolling_engine import Study,CHOICES,SUMMARY_HEADERS,LOG_HEADERS,START_DATE,good
from rolling_log_updates import plan_delta_log_updates
from quote_quality import quote_prices
from comparison_capture import Capture
from measurement_log import EvidenceWriter,DELTA_HEADERS,EXEC_HEADERS,delta_rows,execution_rows
IST=ZoneInfo('Asia/Kolkata');BOOK='1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI';INDEX='NSE:NIFTY50-INDEX'
def now():return datetime.now(IST)
def title(family,choice):return f'{family} - {choice}'
def main():
 import gspread
 from google.oauth2.service_account import Credentials
 from fyers_apiv3 import fyersModel
 from fyers_apiv3.FyersWebsocket import data_ws
 from request_timing import run_with_timeout
 secret=os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON','');token=os.environ.get('FYERS_ACCESS_TOKEN','').strip()
 client=gspread.authorize(Credentials.from_service_account_info(json.loads(secret),scopes=['https://www.googleapis.com/auth/spreadsheets']))
 client.set_timeout((3,8));book=client.open_by_key(BOOK)
 evidence=EvidenceWriter(book);sample_seen=set();sample_pending=[]
 sheets={};existing={w.title:w for w in book.worksheets()}
 for family in ['Time Based','Delta Based']:
  for choice in CHOICES:
   name=title(family,choice)
   for name,headers in [(name,SUMMARY_HEADERS),(name+' Logs',LOG_HEADERS)]:
    ws=existing.get(name) or book.add_worksheet(name,rows=2000,cols=len(headers));values=ws.get_all_values()
    if not values:ws.update(range_name='A1',values=[headers],value_input_option='RAW')
    elif values[0]!=headers:raise RuntimeError('Unexpected schema: '+name)
    sheets[name]=ws
 if os.environ.get('SETUP_ONLY')=='true':print('Six challenger tabs and logs verified; no market requests');return
 if not os.environ.get('GITHUB_RUN_ID'):raise RuntimeError('Normal tracking runs only through the concurrency-protected GitHub workflow')
 day=now().date().isoformat()
 if day<START_DATE or now().weekday()>4 or day in {'2026-11-10','2026-11-24','2026-12-25'}:print('No configured normal session');return
 if now().year!=2026:raise RuntimeError('Update official holiday calendar before a new year')
 for family in ['Time Based','Delta Based']:
  for choice in CHOICES:
   if any(r and r[0]==day for r in sheets[title(family,choice)].get_all_values()[1:]):raise RuntimeError('Existing challenger session; duplicate refused. Inspect saved state before recovery.')
 args=dict(client_id='M2DACFCYUO-100',token=token,log_path='')
 def call(method,payload):
  result=run_with_timeout(lambda:getattr(fyersModel.FyersModel(**args),method)() if method=='get_profile' else getattr(fyersModel.FyersModel(**args),method)(payload),6)
  if result.get('s')!='ok':raise RuntimeError(f'FYERS {method} error {result.get("code")}')
  return result
 if call('get_profile',{}).get('s')!='ok':raise RuntimeError('Authentication unavailable')
 req=urllib.request.Request('https://public.fyers.in/sym_details/NSE_FO.csv',headers={'User-Agent':'NiftyPaperResearch'})
 with urllib.request.urlopen(req,timeout=15) as response:text=response.read().decode('utf-8-sig')
 options={};monthly=set()
 for f in csv.reader(io.StringIO(text)):
  if len(f)<17 or f[13]!='NIFTY':continue
  expiry=datetime.fromtimestamp(int(f[8]),IST).date().isoformat()
  if expiry<day:continue
  if f[16] in ('CE','PE'):options.setdefault(expiry,{})[(int(float(f[15])),f[16])]=f[9]
  elif f[9].endswith('FUT'):monthly.add(expiry)
 metadata=call('optionchain',dict(symbol=INDEX,strikecount=1,timestamp='',greeks='1'))['data']
 listed={datetime.fromtimestamp(int(x['expiry']),IST).date().isoformat():str(x['expiry']) for x in metadata['expiryData']}
 available=sorted(x for x in options if x in listed)
 if len(available)<2:raise RuntimeError('Insufficient cross-verified expiries')
 month=min(monthly)
 if month not in available:raise RuntimeError('Monthly expiry not cross-verified')
 expiry_map=dict(zip(CHOICES,[available[0],available[1],month]));studies=[Study(f,c,expiry_map[c],day) for f in ['Time Based','Delta Based'] for c in CHOICES]
 comparison_capture=Capture(day,'rolling')
 lock=threading.RLock();prices={};chains={};subscriptions=set();connected=threading.Event();ever_connected=False;disconnected=None
 metadata_notes=[];vix_result={};vix_started=False;reset_diagnostics={};reset_attempts={}
 def fetch_vix():
  # Optional context runs independently; it cannot block entry/reset quote processing.
  try:
   response=call('quotes',{'symbols':'NSE:INDIAVIX-INDEX'})
   value=quote_prices(response,['NSE:INDIAVIX-INDEX'])['NSE:INDIAVIX-INDEX']
   with lock:vix_result.update(value=value,at=now().isoformat())
  except Exception as error:
   with lock:vix_result.update(error=type(error).__name__,at=now().isoformat())
 def on_message(message):
  if not isinstance(message,dict):return
  symbol=message.get('symbol');price=message.get('ltp')
  if symbol and good(price) and price>0:
   with lock:
    stamp=now().isoformat();comparison_capture.quote(stamp,symbol,price);prices[symbol]=(price,time.monotonic())
    if '09:30:00'<=stamp[11:19]<'15:00:00':
     for study in studies:study.tick(symbol,price,stamp)
 def on_connect():connected.set()
 def on_close(message):connected.clear()
 socket=data_ws.FyersDataSocket(access_token='M2DACFCYUO-100:'+token,log_path='',litemode=True,write_to_file=False,reconnect=True,on_connect=on_connect,on_close=on_close,on_error=lambda m:print('Socket warning; inspect coverage'),on_message=on_message)
 threading.Thread(target=socket.connect,daemon=True).start()
 seen={name:{r[0] for r in ws.get_all_values()[1:] if r} for name,ws in sheets.items() if name.endswith(' Logs')};row_numbers={}
 for study in studies:
  name=title(study.family,study.choice);row_numbers[name]=len(sheets[name].get_all_values())+1
 def persist():
  at=now().isoformat()
  with lock:
   state={'asof':at,'studies':[__import__('dataclasses').asdict(study) for study in studies]}
   summaries=[(title(study.family,study.choice),study.summary(at)) for study in studies]
   logsets=[(title(study.family,study.choice)+' Logs',study.logs()) for study in studies]
   delta_evidence=delta_rows(studies);execution_evidence=execution_rows(studies)
   pending_samples=list(sample_pending);sample_pending.clear()
  state['reset_diagnostics']=dict(reset_diagnostics);state['metadata']=dict(vix_result)
  if pending_samples:
   with Path('delta_observations.jsonl').open('a',encoding='utf-8') as output:
    for sample in pending_samples:output.write(json.dumps(sample)+'\n')
  # Sheet calls stay outside the quote-processing lock; optional evidence failure cannot stop tracking.
  try:
   evidence.save('Delta Measurements',DELTA_HEADERS,delta_evidence,update=True)
   evidence.save('Execution Measurements',EXEC_HEADERS,execution_evidence)
  except Exception as error:print('Measurement checkpoint pending:',type(error).__name__)
  Path('rolling_state.json').write_text(json.dumps(state,indent=2))
  Path('rolling_quote_diagnostics.json').write_text(json.dumps({'asof':at,'resets':dict(reset_diagnostics),'metadata':dict(vix_result)},indent=2))
  for _,row in summaries:
   if metadata_notes:row[9]+='; '+'; '.join(metadata_notes)
  updates=[]
  for name,row in summaries:updates.append({'range':f"'{name}'!A{row_numbers[name]}",'values':[row]})
  for name,allrows in logsets:
   if name.startswith('Delta Based - '):
    # Re-read outside the callback lock. Same-ID updates finalize entry rows,
    # and a retry after an uncertain write cannot append another copy.
    existing_rows=sheets[name].get_all_values()
    updates.extend(plan_delta_log_updates(name,existing_rows,allrows))
    continue
   rows=[r for r in allrows if r[0] not in seen[name]]
   if rows:
    known={r[0] for r in sheets[name].get_all_values()[1:] if r};rows=[r for r in rows if r[0] not in known]
    if rows:sheets[name].append_rows(rows,value_input_option='RAW')
    seen[name]=known|{r[0] for r in rows}
  book.values_batch_update({'valueInputOption':'RAW','data':updates})
  dashboard=os.environ.get('STRADDLE_DASHBOARD_TOKEN','')
  if dashboard:
   import requests
   for name,_ in summaries:
    for tab in [name,name+' Logs']:
     payload={'spreadsheetId':BOOK,'sheet':tab,'values':sheets[tab].get_all_values()}
     result=requests.post('https://nifty-straddle-lab.cosmicbay1.chatgpt.site/api/sync',json=payload,headers={'OAI-Sites-Authorization':'Bearer '+dashboard},timeout=12)
     if result.status_code!=200:print('Dashboard sync pending:',tab,result.status_code)
 save_thread=None;save_errors=[]
 def save_background():
  try:persist()
  except Exception as e:save_errors.append(type(e).__name__);print('Sheet checkpoint failed:',type(e).__name__)
 def pair_for(expiry,mono):
  cached=chains.get(expiry)
  if not cached or mono-cached['at']>30:return None,{},{}
  d=cached['data'];rows=d['optionsChain'];spot=next((x.get('ltp') for x in rows if x.get('option_type') not in ['CE','PE']),None)
  if not good(spot) or spot<=0:return None,{},{}
  strike=int((spot+25)//50)*50;pair={'at':cached['at'],'spot':spot,'strike':strike};gs={};qs={sym:p for sym,(p,received) in prices.items() if 0<=mono-received<=10}
  for x in rows:
   sym=x.get('symbol');delta=x.get('greeks',{}).get('delta')
   if good(delta):gs[sym]=delta
   tick=prices.get(sym)
   if tick and mono-tick[1]<=10:qs[sym]=tick[0]
   if x.get('option_type') in ('CE','PE') and x.get('strike_price')==strike:
    side=x['option_type'];exact=options[expiry].get((strike,side))
    if exact!=sym:return None,gs,qs
    pair[side]={'symbol':sym,'price':qs.get(sym),'delta':delta}
  if not all(s in pair for s in ('CE','PE')):return None,gs,qs
  return pair,gs,qs
 unique=sorted(set(expiry_map.values()));which=0;next_chain=0;next_save=0;last_monotonic=time.monotonic();final=False
 while True:
  t=now();clock=t.time();mono=time.monotonic()
  if not vix_started and clock>=dt_time(9,30):
   vix_started=True;threading.Thread(target=fetch_vix,daemon=True).start()
  if vix_result and not metadata_notes:
   with lock:
    if 'value' in vix_result:
     for study in studies:study.vix=vix_result['value']
     metadata_notes.append('VIX retrieved '+vix_result['at']+'; response-time snapshot, not guaranteed exact entry')
    else:metadata_notes.append('VIX unavailable at '+vix_result['at']+'; '+vix_result['error'])
  if mono-last_monotonic>15 and clock>=dt_time(9,30):
   for study in studies:study.issue('Collector processing gap >15 seconds')
  last_monotonic=mono
  if clock>=dt_time(15,0):
   if not final:
    with lock:
     symbols=sorted({l.symbol for s in studies for sc in s.scenarios.values() if sc.active for l in sc.active.open_legs()})
    for i in range(0,len(symbols),50):
     try:
      response=call('quotes',{'symbols':','.join(symbols[i:i+50])})
      with lock:
       for x in response['d']:
        v=x.get('v',{});lp=v.get('lp')
        if good(lp) and lp>0:prices[x['n']]=(lp,time.monotonic())
     except Exception as error:
      print('Final quote request unavailable:',type(error).__name__)
      for study in studies:study.issue('Final REST quote unavailable; review final coverage')
    with lock:
     quotes={s:p for s,(p,age) in prices.items() if time.monotonic()-age<=10}
     for study in studies:study.advance(now().isoformat(),None,quotes,{},time.monotonic())
     for study in studies:
      if not all(sc.done for sc in study.scenarios.values()):study.issue('INCOMPLETE final quotes')
    if save_thread:save_thread.join(timeout=180)
    if save_thread and save_thread.is_alive():raise RuntimeError('Prior checkpoint did not finish; finalization requires review')
    persist();print('Paper session finalized; no broker orders');final=True
   break
  if mono>=next_chain:
   expiry=unique[which%len(unique)];which+=1;next_chain=mono+5
   try:
    requested=now().isoformat();d=call('optionchain',dict(symbol=INDEX,strikecount=50,timestamp=listed[expiry],greeks='1'))['data'];chains[expiry]={'at':time.monotonic(),'data':d,'requested':requested};comparison_capture.chain(now().isoformat(),expiry,d)
   except Exception as error:
    print('Chain request unavailable:',type(error).__name__)
    if clock>=dt_time(9,30):
     for study in studies:
      if study.expiry==expiry:study.issue('Chain snapshot unavailable')
  # After the post-slot chain selects ATM, obtain both entry contracts and
  # every surviving outgoing leg in one bounded request when ticks are absent.
  # Network IO remains outside the callback lock; the engine still enforces
  # the original 30-second reset deadline and max-three-entry rules.
  slot=next((x for x in ('11:20:00','13:10:00') if x<=t.strftime('%H:%M:%S')<=x[:6]+'30'),None)
  if slot:
   for expiry in unique:
    key=day+'|'+expiry+'|'+slot
    with lock:
     targets=[s for s in studies if s.family=='Time Based' and s.expiry==expiry and any(sc.active and slot not in sc.handled_slots for sc in s.scenarios.values())]
     pair,_,qs=pair_for(expiry,time.monotonic());cached=chains.get(expiry,{})
     needed=({pair[s]['symbol'] for s in ('CE','PE')} if pair else set())|{l.symbol for s in targets for sc in s.scenarios.values() if sc.active for l in sc.active.open_legs()}
     missing=sorted(needed-set(qs))
    if not targets:continue
    reason='POST-SLOT CHAIN PENDING' if not pair or cached.get('requested','')[11:19]<slot else 'FRESH QUOTES MISSING: '+','.join(missing) if missing else 'READY'
    reset_diagnostics[key]={'at':now().isoformat(),'readiness':reason}
    if reason.startswith('FRESH QUOTES MISSING') and time.monotonic()-reset_attempts.get(key,-1e10)>=7:
     reset_attempts[key]=time.monotonic()
     def reset_quotes(key=key,needed=sorted(needed),missing=missing):
      try:
       response=call('quotes',{'symbols':','.join(needed)});fresh=quote_prices(response,needed);received=now().isoformat()
       with lock:
        for symbol,price in fresh.items():
         prices[symbol]=(price,time.monotonic())
         for study in studies:study.tick(symbol,price,received)
        reset_diagnostics[key]={'at':received,'readiness':'REST RESPONSE RECEIVED; engine deadline still applies','symbols':needed}
      except Exception as error:
       with lock:reset_diagnostics[key]={'at':now().isoformat(),'readiness':'REST FALLBACK FAILED','error':type(error).__name__,'missing':missing}
     threading.Thread(target=reset_quotes,daemon=True).start()
  with lock:
   for study in studies:
    pair,gs,qs=pair_for(study.expiry,time.monotonic())
    if pair:
     wanted={pair[s]['symbol'] for s in ('CE','PE')}
     wanted|={l.symbol for sc in study.scenarios.values() if sc.active for l in sc.active.open_legs()}
     if connected.is_set() and wanted-subscriptions:socket.subscribe(symbols=sorted(wanted-subscriptions),data_type='SymbolUpdate');subscriptions|=wanted
     if clock>=dt_time(9,30):
      if study.family=='Delta Based' and any(l.symbol not in gs for sc in study.scenarios.values() if sc.active and sc.active.open_legs() and len(sc.cycles)<3 for l in sc.active.legs.values()):study.issue('Original-pair Greeks missing; delta rolls paused')
      snapshot_clock=chains[study.expiry]['requested'][11:19]
      needs_clock='09:30:00' if not study.initial_at else '13:10:00' if study.family=='Time Based' and now().time()>=dt_time(13,10) else '11:20:00' if study.family=='Time Based' and now().time()>=dt_time(11,20) else '00:00:00'
      if snapshot_clock>=needs_clock:
       observed=chains[study.expiry]['requested']
       study.observe_delta(now().isoformat(),gs,observed)
       study.advance(now().isoformat(),pair,qs,gs,time.monotonic())
       study.observe_delta(now().isoformat(),gs,observed)
       for row in delta_rows([study]):
        key=(row[0],row[9])
        if row[9] and key not in sample_seen:sample_seen.add(key);sample_pending.append(dict(zip(DELTA_HEADERS,row)))
    elif clock>dt_time(9,35) and not study.initial_at:study.issue('MISSED ENTRY WINDOW')
   if clock>=dt_time(9,30):
    if not connected.is_set():
     if disconnected is None:disconnected=mono
     if mono-disconnected>10:
      for study in studies:study.issue('WebSocket gap >10 seconds; review stop coverage')
    else:disconnected=None
  if clock>=dt_time(9,30) and mono>=next_save:
   if not save_thread or not save_thread.is_alive():
    save_thread=threading.Thread(target=save_background,daemon=True);save_thread.start()
   next_save=mono+30
  time.sleep(.5)
 comparison_capture.close()
 if hasattr(socket,'close_connection'):socket.close_connection()
if __name__=='__main__':main()






