"""Allowlisted paper-only fallback dispatcher for an independent cloud wake-up."""
import argparse
import json
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from automation_dispatch import GitHub, ACTIVE
from market_calendar import session_allowed

IST = ZoneInfo('Asia/Kolkata')
BOOK = '1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI'
TARGETS = {
    'fixed': ('straddle.yml', time(8,55), time(9,25), {'test_mode':'false','setup_only':'false'}, ['Straddle Fixed Summary']),
    'rolling': ('rolling-straddles.yml', time(8,55), time(9,25), {'setup_only':'false'}, ['Time Based Summary','Delta Based Summary']),
    'strangle': ('short-strangle.yml', time(9,10), time(9,25), {'mode':'collect'}, ['Short Strangle Summary']),
    'abc': ('abc-equity-paper.yml', time(8,55), time(9,10), {'collect':'true'}, []),
    'close': ('short-strangle.yml', time(15,7), time(18,0), {'mode':'verify'}, []),
    'study': ('nifty-study.yml', time(16,30), time(23,30), {'connection_check':'false'}, []),
    'stocks': ('short-term-calls.yml', time(8,50), time(18,30), {'connection_check':'false'}, []),
}

def same_day(run, now):
    return datetime.fromisoformat(run['created_at'].replace('Z','+00:00')).astimezone(IST).date() == now.date()

def relevant(key, run, now):
    if run.get('head_branch','main') != 'main': return False
    event = run.get('event')
    if event not in ('schedule','workflow_dispatch'): return False
    title = run.get('display_title','').lower()
    if 'setup' in title or 'connection check' in title or 'test mode' in title: return False
    if key == 'abc' and 'shared sheet check' in title: return False
    if key in ('strangle','close'):
        created = datetime.fromisoformat(run['created_at'].replace('Z','+00:00')).astimezone(IST)
        # New run titles distinguish modes. Legacy ambiguous afternoon runs block
        # a second dispatch for review rather than risk duplicate collection.
        if key == 'strangle' and 'verify' in title: return False
        if key == 'close':
            if 'collect' in title: return False
            if 'verify' not in title and created.time() < time(15,0): return False
    if key == 'stocks':
        created = datetime.fromisoformat(run['created_at'].replace('Z','+00:00')).astimezone(IST)
        return run.get('status') in ACTIVE or created >= now - timedelta(minutes=14)
    return run.get('status') in ACTIVE or same_day(run,now)

def check(api, key, now, has_entry, dry_run=False):
    workflow, start, end, inputs, tabs = TARGETS[key]
    if not start <= now.time() < end:
        return {'target':key,'status':'NOT DUE'}
    def blockers():
        return [r for r in api.runs(workflow) if relevant(key,r,now)]
    found = blockers()
    if found:
        return {'target':key,'status':'EXISTS','runs':[r['html_url'] for r in found]}
    if tabs and has_entry(tabs,now.date().isoformat()):
        return {'target':key,'status':'SHEET PRESENT; NO RESTART'}
    if dry_run: return {'target':key,'status':'WOULD DISPATCH'}
    if blockers(): return {'target':key,'status':'RACING RUN; NO DISPATCH'}
    # Check real time again after remote reads. Never let slow calls extend entry cutoff.
    current = datetime.now(IST)
    if current.date() != now.date() or not start <= current.time() < end:
        return {'target':key,'status':'WINDOW ENDED'}
    api.dispatch(workflow,inputs)
    return {'target':key,'status':'DISPATCH ACCEPTED; START UNVERIFIED'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();now=datetime.now(IST)
    if os.getenv('GITHUB_EVENT_NAME')=='push':
        request=json.loads(Path('.automation/cloud-wakeup.json').read_text())
        issued=datetime.fromisoformat(request['issued_at'])
        if issued.tzinfo is None or request['date']!=now.date().isoformat() or not 0 <= (now-issued).total_seconds() <= 900:
            raise RuntimeError('Stale, future or wrong-session cloud wake-up')
    allowed,reason=session_allowed(now.date().isoformat())
    if not allowed:
        if 'outside verified' in reason: raise RuntimeError(reason)
        print(reason);return
    import gspread
    from google.oauth2.service_account import Credentials
    client=gspread.authorize(Credentials.from_service_account_info(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']))
    client.set_timeout((3,10));book=client.open_by_key(BOOK)
    def has_entry(tabs,day):
        return any(any(r and r[0]==day for r in book.worksheet(tab).get('A2:A2000')) for tab in tabs)
    api=GitHub(os.environ['GH_TOKEN'])
    results=[check(api,key,now,has_entry,args.dry_run) for key in TARGETS]
    report={'checked_at':now.isoformat(),'dry_run':args.dry_run,'results':results}
    Path('session-control-report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as out:
            out.write('## Paper workflow fallback\n'+ '\n'.join('- '+r['target']+': '+r['status'] for r in results))

if __name__=='__main__':main()

