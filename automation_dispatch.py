"""Allowlisted paper workflow dispatcher. Never calls broker order endpoints."""
import json,os,time
from datetime import datetime,timezone,time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import re
from market_calendar import session_allowed
IST=ZoneInfo('Asia/Kolkata');REPO='samuelputla/NIFTY-Straddle'
BOOK='1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI'
WORKFLOWS={
 'straddle.yml':({'test_mode':'false','setup_only':'false'},['Current Week Expiry','Next Week Expiry','Monthly Expiry']),
 'rolling-straddles.yml':({'setup_only':'false'},[f'{family} - {choice}' for family in ['Time Based','Delta Based'] for choice in ['Current Week','Next Week','Monthly']]),
 'daily-straddle-research.yml':({},['Daily Straddle Research'])}
ACTIVE={'queued','in_progress','waiting','requested','pending'}
class GitHub:
 def __init__(self,token,base='https://api.github.com'):
  self.base=base;self.session=requests.Session();self.session.headers.update(Authorization='Bearer '+token,Accept='application/vnd.github+json',**{'X-GitHub-Api-Version':'2022-11-28'})
 def runs(self,workflow):
  # Current-day normal requests plus all queued/running runs, even from yesterday.
  result=[]
  for page in range(1,4):
   r=self.session.get(f'{self.base}/repos/{REPO}/actions/workflows/{workflow}/runs',params={'branch':'main','per_page':100,'page':page},timeout=(3,12));r.raise_for_status();runs=r.json()['workflow_runs'];result.extend(runs)
   if len(runs)<100:break
  else:raise RuntimeError('Workflow pagination incomplete; dispatch refused')
  return result
 def dispatch(self,workflow,inputs):
  r=self.session.post(f'{self.base}/repos/{REPO}/actions/workflows/{workflow}/dispatches',json={'ref':'main','inputs':inputs},timeout=(3,12));r.raise_for_status()
  if r.status_code not in (200,204):raise RuntimeError('Unexpected dispatch response')
def current_day(run,day):
 return datetime.fromisoformat(run['created_at'].replace('Z','+00:00')).astimezone(IST).date().isoformat()==day
def blocker(runs,day):
 active=[r for r in runs if r.get('status') in ACTIVE]
 if active:return 'Existing queued/waiting/running instance',active
 today=[r for r in runs if current_day(r,day)]
 if today:return 'Existing current-day run; failed/partial runs require review, not an automatic rerun',today
 return '',[]
def safe_dispatch(api,workflow,inputs,day,has_entry,now_fn=lambda:datetime.now(IST),kind='start'):
 def relevant(runs):
  if kind!='audit':return runs
  # An explicitly dated past-session verification is not today's scheduled audit.
  def keep(r):
   date=re.search(r'\d{4}-\d{2}-\d{2}',r.get('display_title',''))
   return r.get('status') in ACTIVE or date is None or date.group()==day
  return [r for r in runs if keep(r)]
 clock=now_fn()
 if clock.date().isoformat()!=day:return {'workflow':workflow,'status':'SKIPPED','reason':'Date changed'}
 if kind=='start' and not dt_time(8,45)<=clock.time()<dt_time(9,25):return {'workflow':workflow,'status':'SKIPPED','reason':'Outside 08:45–09:25 IST start window; never dispatch late positions'}
 if kind=='audit' and clock.time()<dt_time(16,7):return {'workflow':workflow,'status':'SKIPPED','reason':'Audit is not due yet'}
 reason,runs=blocker(relevant(api.runs(workflow)),day)
 if reason:return {'workflow':workflow,'status':'SKIPPED','reason':reason,'runs':[r['html_url'] for r in runs]}
 if has_entry(workflow):return {'workflow':workflow,'status':'SKIPPED','reason':'Existing current-date Sheet row; inspect partial capture'}
 # Recheck immediately before mutation; workflow concurrency and collectors'
 # own Sheet guards remain the final protection against a racing manual run.
 reason,runs=blocker(relevant(api.runs(workflow)),day)
 if reason:return {'workflow':workflow,'status':'SKIPPED','reason':reason,'runs':[r['html_url'] for r in runs]}
 clock=now_fn()
 if kind=='start' and clock.time()>=dt_time(9,25):return {'workflow':workflow,'status':'SKIPPED','reason':'Start window ended during checks'}
 api.dispatch(workflow,inputs)
 for attempt in range(6):
  runs=[r for r in relevant(api.runs(workflow)) if current_day(r,day)]
  if runs:
   r=max(runs,key=lambda r:r['id']);return {'workflow':workflow,'status':'DISPATCH VERIFIED','run_id':r['id'],'run_status':r['status'],'url':r['html_url']}
  time.sleep(2)
 return {'workflow':workflow,'status':'REVIEW','reason':'Dispatch accepted but new run ID not visible; no second dispatch attempted'}
def main():
 request=json.loads(Path('.automation/request.json').read_text(encoding='utf-8'));now=datetime.now(IST);day=now.date().isoformat();kind=request.get('kind')
 if kind=='disabled':print('Initial control request disabled; no dispatch');return
 if request.get('date')!=day:raise RuntimeError('Request date is not current IST date')
 issued=datetime.fromisoformat(request['issued_at']);age=(now-issued.astimezone(IST)).total_seconds()
 if not 0<=age<=15*60:raise RuntimeError('Expired or future request; refused')
 allowed,reason=session_allowed(day)
 if not allowed:
  if 'outside verified' in reason:raise RuntimeError(reason)
  print(reason);return
 if kind not in ('start','audit','healthcheck'):raise RuntimeError('Unknown request kind')
 api=GitHub(os.environ['GH_TOKEN'])
 if kind=='healthcheck':
  results=[{'workflow':w,'visible_runs':len(api.runs(w))} for w in WORKFLOWS]
  # Exercise the exact unattended GITHUB_TOKEN dispatch capability against
  # this workflow's inert probe job, never a running collector.
  known={r['id'] for r in api.runs('automation-dispatch.yml')}
  api.dispatch('automation-dispatch.yml',{'probe':'true'})
  for attempt in range(6):
   new=[r for r in api.runs('automation-dispatch.yml') if r['id'] not in known and r.get('event')=='workflow_dispatch']
   if new:
    probe=max(new,key=lambda r:r['id']);results.append({'workflow':'permission-probe','status':'DISPATCH VERIFIED','run_id':probe['id'],'run_status':probe['status'],'url':probe['html_url']});break
   time.sleep(2)
  else:results.append({'workflow':'permission-probe','status':'REVIEW','reason':'Probe dispatch accepted but no new run ID visible'})
 elif kind=='audit':results=[safe_dispatch(api,'eod-validation.yml',{},day,lambda _:False,kind='audit')]
 else:
  import gspread
  from google.oauth2.service_account import Credentials
  client=gspread.authorize(Credentials.from_service_account_info(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']));client.set_timeout((3,10));book=client.open_by_key(BOOK)
  def has_entry(workflow):
   for tab in WORKFLOWS[workflow][1]:
    if any(r and r[0]==day for r in book.worksheet(tab).get('A2:A1000')):return True
   return False
  results=[safe_dispatch(api,w,inputs,day,has_entry) for w,(inputs,_) in WORKFLOWS.items()]
 Path('dispatch-report.json').write_text(json.dumps({'day':day,'kind':kind,'results':results},indent=2),encoding='utf-8')
 summary='\n'.join(f"- {r.get('workflow')}: {r.get('status','HEALTHCHECK')} {r.get('reason','')} {r.get('url','')}" for r in results)
 print(summary)
 if os.getenv('GITHUB_STEP_SUMMARY'):
  with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:f.write('# Automatic paper workflow control\n'+summary+'\n')
 if any(r.get('status')=='REVIEW' for r in results):raise RuntimeError('Dispatch requires review; see report')
if __name__=='__main__':main()

