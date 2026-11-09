"""Prepare swing research, track frozen calls, and journal reviews in five existing tabs."""
import argparse
import json
import os
from pathlib import Path
from datetime import datetime,timedelta,time
from .engine import IST,VERSION,session,stamp,replay
from .providers import History,DataUnavailable
from .storage import Store,BOOK
from .portfolio import summary
from .swing import prepare,next_session,latest_session
from .learning import save_reviews,challenger_report,market_audit

OUT=Path('short-term-report')

def connect_store():
    import gspread
    from google.oauth2.service_account import Credentials
    from sheets_resilience import ResilientHTTPClient
    client=gspread.authorize(Credentials.from_service_account_info(
        json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),
        scopes=['https://www.googleapis.com/auth/spreadsheets']),http_client=ResilientHTTPClient)
    client.set_timeout((5,15))
    return Store(client.open_by_key(BOOK))

def install_registry(store,now):
    for p in json.loads(Path('short_term_calls/plans.json').read_text())['calls']:
        if p['id'] in {x['id'] for x in store.plans()}:continue
        if now>=stamp(p['start_at']):
            store.journal_once(p['id'],'Missed Installation Window',now.isoformat(),
                               'Forecast was not registered before its start; no retroactive paper entry or P&L created')
            continue
        store.register(p,now.isoformat())
        store.save_result(p,replay(p,[],now.isoformat()))
        store.journal_once(p['id'],'Frozen Forecast Installed',now.isoformat(),
                           {'source':p['source'],'rule':p.get('entry_rule','Breakout Retest Confirmation'),
                            'target_session':p['start_at'][:10],'entry_min':p['entry_min'],
                            'entry_max':p['entry_max'],'stop':p['stop'],'target1':p['target_1']})

def track(store,history,now):
    plans=store.plans();prior=store.results();active=[];results=[]
    for p in plans:
        if not stamp(p['start_at'])<=now<=stamp(p['observe_until'])+timedelta(days=1):continue
        prev=prior.get(p['id'],{})
        if prev.get('status') in ('Closed','Cancelled','Expired Unfilled'):
            if now.time().replace(tzinfo=None)<time(15,35):continue
            if prev.get('as_of') and stamp(prev['as_of']).date()==now.date() and stamp(prev['as_of']).time().replace(tzinfo=None)>=time(15,35):continue
        active.append(p)
    for sym in sorted({p['symbol'] for p in active}):
        group=[p for p in active if p['symbol']==sym]
        def begin(p):
            return stamp(p['start_at']) if p.get('monitor_from_start') else stamp(p['issued_at']).replace(second=0,microsecond=0)+timedelta(minutes=1)
        start=min(begin(p) for p in group);finish=min(now,max(stamp(p['observe_until']) for p in group))
        try:
            raw=history.fetch(sym,start,finish)
            for p in group:
                r=replay(p,raw,now.isoformat());store.save_result(p,r);results.append(r)
        except DataUnavailable as exc:
            store.journal(sym,'Tracking Data Unavailable',now.isoformat(),str(exc))
            if 'rate limit' in str(exc).lower() or 'authentication' in str(exc).lower():raise
    save_reviews(store,plans,results,OUT,now)
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection-check',action='store_true')
    parser.add_argument('--prepare',action='store_true',help='Prepare next eligible session outside market hours')
    args=parser.parse_args()
    if not os.getenv('GITHUB_RUN_ID'):raise RuntimeError('Run using the concurrency-protected GitHub workflow')
    OUT.mkdir(exist_ok=True)
    now=datetime.now(IST).replace(microsecond=0)
    run_id=os.environ['GITHUB_RUN_ID']+'-'+os.getenv('GITHUB_RUN_ATTEMPT','1')
    url='https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID']
    store=None
    try:
        store=connect_store();config=json.loads(Path('short_term_calls/config.json').read_text())
        install_registry(store,now)
        # Register future forecasts before checking external market-data access.
        history=History(OUT)
        allowed=session(now.date());clock=now.time().replace(tzinfo=None)
        if args.connection_check:
            prior=latest_session(now.date() if clock>=time(15,35) else now.date()-timedelta(days=1))
            daily=history.daily('NSE:ICICIBANK-EQ',prior)
            if len(daily)<60:raise DataUnavailable('Connection check: daily warm-up incomplete')
            minutes=history.fetch('NSE:ICICIBANK-EQ',datetime.combine(prior,time(9,15),IST),datetime.combine(prior,time(15,30),IST))
            if len(minutes)!=375:raise DataUnavailable('Connection check: prior normal session has missing minutes')
            store.run(run_id,now.isoformat(),'Connection','Passed',len(store.plans()),
                      'Daily indicator history, 375 equity minutes and five-tab Sheet journal verified; future sealed forecasts installed',url,VERSION)
            store.portfolio(summary(store.plans(),store.results(),config['portfolio'],now.isoformat()))
            return
        results=[]
        if allowed and clock>=time(9,15):results=track(store,history,now)
        if allowed and time(9,50)<=clock<=time(14,30):
            try:
                generated=prepare(store,history,now.date(),now,OUT,config,live=True)
                store.run(run_id,datetime.now(IST).isoformat(),'Market Generation','Passed',len(generated),
                          'Fresh timestamped swing calls from prior daily indicators and completed opening/fresh minute evidence; existing plans never replaced',url,VERSION)
            except DataUnavailable as exc:
                store.run(run_id,datetime.now(IST).isoformat(),'Market Generation','Unavailable',0,str(exc),url,VERSION)
                if 'rate limit' in str(exc).lower() or 'authentication' in str(exc).lower():raise
        # A scheduled preparation is sealed before the target opens. No late morning forecasts.
        if clock<time(9,10) or clock>=time(15,35):
            target=now.date() if allowed and clock<time(9,10) else next_session(now.date())
            try:
                generated=prepare(store,history,target,now,OUT,config)
                store.run(run_id,datetime.now(IST).isoformat(),'Preparation','Passed',len(generated),
                          'Target '+target.isoformat()+'; Swing Breakout Retest V3; qualified unselected calls retained for research; see Radar Snapshots',url,VERSION)
            except DataUnavailable as exc:
                store.run(run_id,datetime.now(IST).isoformat(),'Preparation','Unavailable',0,str(exc),url,VERSION)
                if 'rate limit' in str(exc).lower() or 'authentication' in str(exc).lower():raise
        elif args.prepare:
            store.run(run_id,now.isoformat(),'Preparation','Skipped',0,'Market already open; no backdated forecasts',url,VERSION)
        if allowed and clock>=time(18,0):
            try:market_audit(store,now.date(),store.plans(),OUT,now)
            except DataUnavailable as exc:store.run(run_id,now.isoformat(),'Coverage','Unavailable',0,str(exc),url,VERSION)
        learning=challenger_report(store.plans(),store.results())
        (OUT/'challenger-comparison.json').write_text(json.dumps(learning,indent=2))
        if allowed and clock>=time(18,0):
            store.journal_once(now.date().isoformat(),'Pattern Change Review',now.isoformat(),learning)
        store.portfolio(summary(store.plans(),store.results(),config['portfolio'],now.isoformat()))
        store.run(run_id,now.isoformat(),'Tracking','Passed',len(results),
                  'Paper only; one share; T1 full exit; new swing calls require breakout/retest. Frozen breakout-only seeds retain original rules. '+('normal session' if allowed else 'market closed'),url,VERSION)
        (OUT/'results.json').write_text(json.dumps(results,indent=2))
        print(json.dumps({'status':'PASSED','tracked':len(results),'paper_only':True,'workflow':url}))
    except Exception as exc:
        safe=str(exc) if isinstance(exc,(ValueError,DataUnavailable)) else 'Integration failed: '+type(exc).__name__
        (OUT/'failure.json').write_text(json.dumps({'status':'FAILED','reason':safe,'as_of':now.isoformat()}))
        if store is not None:
            try:store.run(run_id,now.isoformat(),'Failure','Failed',0,safe,url,VERSION)
            except Exception:pass
        print('SHORT TERM FAILED: '+safe)
        raise SystemExit(1)
