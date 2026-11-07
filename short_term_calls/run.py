"""One cloud workflow: generate frozen paper calls and audit their subsequent price paths."""
import argparse
import json
import os
import sys
from datetime import datetime,timedelta,time
from pathlib import Path
from .engine import IST,VERSION,session,stamp,replay,digest
from .generate import DEFAULTS,daily_candidates,make_plan
from .providers import History,DataUnavailable
from .storage import Store,BOOK
from .portfolio import select as select_portfolio,summary as portfolio_summary

OUT=Path('short-term-report')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection-check',action='store_true')
    args=parser.parse_args()
    if not os.getenv('GITHUB_RUN_ID'):raise RuntimeError('Run using the concurrency-protected GitHub workflow')
    OUT.mkdir(exist_ok=True)
    now=datetime.now(IST).replace(microsecond=0)
    run_id=os.environ['GITHUB_RUN_ID']+'-'+os.getenv('GITHUB_RUN_ATTEMPT','1')
    workflow_url='https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID']
    store=None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        from sheets_resilience import ResilientHTTPClient
        client=gspread.authorize(Credentials.from_service_account_info(
            json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),
            scopes=['https://www.googleapis.com/auth/spreadsheets']),http_client=ResilientHTTPClient)
        client.set_timeout((5,15))
        store=Store(client.open_by_key(BOOK))
        history=History(OUT)
        plans=store.plans()
        config=json.loads(Path('short_term_calls/config.json').read_text())
        settings={**DEFAULTS,**config['selection']}
        portfolio_settings=config['portfolio']
        registry=json.loads(Path('short_term_calls/plans.json').read_text())['calls']
        for p in registry:store.register(p,now.isoformat())
        plans=store.plans()
        if args.connection_check:
            d=now.date()-timedelta(days=1)
            while not session(d):d-=timedelta(days=1)
            begin=datetime.combine(d,time(9,15),IST)
            end=datetime.combine(d,time(15,30),IST)
            test=history.fetch('NSE:ICICIBANK-EQ',begin,end)
            if len(test)!=375:raise DataUnavailable('Connection check: incomplete prior-session minute history')
            store.run(run_id,now.isoformat(),'Connection','Passed',len(plans),
                      'FYERS 375 completed equity minutes and Sheet write verified; no test calls created',workflow_url,VERSION)
            store.portfolio(portfolio_summary(plans,store.results(),portfolio_settings,now.isoformat()))
            print('CONNECTION PASSED: FYERS equity history and stock-call Sheet journal')
            return
        if now.date()<stamp(config['start_at']).date():
            store.run(run_id,now.isoformat(),'Tracking','Scheduled',len(plans),'Starts 9 November 2026',workflow_url,VERSION)
            return
        allowed=session(now.date())
        # Reconstruct existing calls first, then select fresh calls with the resulting capacity.
        cache={}
        prior=store.results()
        active=[]
        for p in plans:
            if not stamp(p['start_at'])<=now<=stamp(p['observe_until'])+timedelta(days=1):continue
            previous=prior.get(p['id'],{})
            observation_only=previous.get('status') in ('Closed','Cancelled','Expired Unfilled')
            if observation_only:
                # Missed moves and post-exit observations need one full-session audit, not another live request every poll.
                if now.time().replace(tzinfo=None)<time(15,35):continue
                last=stamp(previous['as_of']) if previous.get('as_of') else None
                if last and last.date()==now.date() and last.time().replace(tzinfo=None)>=time(15,35):continue
            active.append(p)
        for symbol in sorted({p['symbol'] for p in active}):
            group=[p for p in active if p['symbol']==symbol]
            begin=min(stamp(p['issued_at']).replace(second=0,microsecond=0)+timedelta(minutes=1) for p in group)
            finish=min(now,max(stamp(p['observe_until']) for p in group))
            if finish<=begin:continue
            cache[symbol]=history.fetch(symbol,begin,finish)
        results=[]
        for p in active:
            result=replay(p,cache.get(p['symbol'],[]),now.isoformat())
            store.save_result(p,result);results.append(result)
        generation_window=allowed and time(9,47)<=now.time().replace(tzinfo=None)<=time(11,0)
        if generation_window and not store.generation_done(now.date().isoformat()):
            today=[p for p in plans if stamp(p['issued_at']).date()==now.date() and p.get('status','Active')=='Active']
            proposed=[];selection_audit=[];generated=[]
            candidates=daily_candidates(now.date(),OUT,settings)
            (OUT/'candidates.json').write_text(json.dumps(candidates,indent=2))
            used={(p['symbol'],p['type']) for p in today}
            try:
                for candidate in candidates:
                    for kind in ('Intraday','Swing'):
                        symbol='NSE:'+candidate['symbol']+'-EQ'
                        if (symbol,kind) in used:continue
                        if symbol not in cache:
                            begin=datetime.combine(now.date(),time(9,15),IST)
                            cache[symbol]=history.fetch(symbol,begin,now)
                        reasons=[]
                        p=make_plan(candidate,kind,cache[symbol],now,settings,reasons.append)
                        selection_audit.append({'symbol':symbol,'type':kind,'result':'Qualified' if p else 'Rejected',
                                                'reason':'; '.join(reasons)})
                        if p is None:continue
                        # Fresh issue timestamp must reflect completion of all provider reads.
                        issued=datetime.now(IST).replace(microsecond=0)
                        p['issued_at']=issued.isoformat()
                        p['start_at']=(issued.replace(second=0)+timedelta(minutes=1)).isoformat()
                        if issued.time().replace(tzinfo=None)>time(11,0):
                            raise DataUnavailable('Generation ran beyond 11:00 cutoff; remaining candidates not issued')
                        proposed.append(p);used.add((symbol,kind))
                # Freeze ranking and portfolio selection before new outcomes or entries can exist.
                issued=datetime.now(IST).replace(microsecond=0)
                if issued.time().replace(tzinfo=None)>time(11,0):
                    raise DataUnavailable('Generation ran beyond 11:00 cutoff; no new calls issued')
                for p in proposed:
                    p['issued_at']=issued.isoformat()
                    p['start_at']=(issued.replace(second=0)+timedelta(minutes=5)).isoformat()
                existing_results=store.results()
                ps=dict(portfolio_settings)
                ps['daily_selection_count']=max(0,ps['daily_selection_count']-sum(p.get('portfolio_selected',False) for p in today))
                generated=select_portfolio(proposed,plans,existing_results,issued,ps)
                store.register_many(generated,issued.isoformat())
                # The next normal tracking run supplies the first market-status rows.
                plans=store.plans()
            finally:
                (OUT/'selection_audit.json').write_text(json.dumps(selection_audit,indent=2))
                (OUT/'new_calls.json').write_text(json.dumps(generated,indent=2))
            status='Generated' if generated else 'No Qualified Calls'
            store.run(run_id,datetime.now(IST).isoformat(),'Generation',status,len(generated),
                      'Versioned price/volume paper rule; fundamentals/news/depth unverified. No orders.',workflow_url,VERSION)
        store.run(run_id,now.isoformat(),'Tracking','Passed',len(results),
                  'One-minute reconstruction; all calls researched, top three selected prospectively for Rs300000 paper account; '+
                  ('normal session' if allowed else 'market closed'),workflow_url,VERSION)
        store.portfolio(portfolio_summary(store.plans(),store.results(),portfolio_settings,datetime.now(IST).isoformat()))
        (OUT/'results.json').write_text(json.dumps(results,indent=2))
        print(json.dumps({'status':'PASSED','tracked':len(results),'method':'paper reconstruction','workflow':workflow_url}))
    except Exception as exc:
        # Never print HTTP response bodies, headers, tokens or account JSON.
        safe=str(exc) if isinstance(exc,(ValueError,DataUnavailable)) else 'Integration failed: '+type(exc).__name__
        (OUT/'failure.json').write_text(json.dumps({'status':'FAILED','reason':safe,'as_of':now.isoformat()}))
        if store is not None:
            try:store.run(run_id,now.isoformat(),'Failure','Failed',0,safe,workflow_url,VERSION)
            except Exception:pass
        print('SHORT TERM FAILED: '+safe)
        raise SystemExit(1)


if __name__=='__main__':main()
