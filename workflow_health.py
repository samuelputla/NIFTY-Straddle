"""Read-only daily execution health for the two additional research workflows."""
import json,os,sys
from datetime import datetime,time
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from market_calendar import session_allowed
from nifty_study.calendar import session as equity_session
IST=ZoneInfo('Asia/Kolkata');REPO='samuelputla/NIFTY-Straddle'
TARGETS={'short-strangle.yml':{'name':'Short Strangle Paper Research','start':time(9,10),'ready':time(9,20),'finish':time(15,15)},'nifty-study.yml':{'name':'Nifty study','start':time(16,30),'ready':time(16,40),'finish':time(17,5)}}
ACTIVE={'queued','in_progress','waiting','requested','pending'}
ALERTS={'MISSING','QUEUED','FAILED','STALLED','REVIEW','ACCESS ERROR'}
def expected(workflow,day):
 if workflow=='nifty-study.yml':return equity_session(day) is not None
 allowed,reason=session_allowed(day)
 if not allowed and 'outside verified' in reason:raise ValueError(reason)
 return allowed

def evaluate(workflow,runs,now):
 config=TARGETS[workflow];day=now.date().isoformat();clock=now.time().replace(tzinfo=None)
 result={'workflow':workflow,'name':config['name'],'checked_at_ist':now.isoformat(),'date':day,'runs':[]}
 try:due=expected(workflow,day)
 except ValueError as e:return {**result,'status':'REVIEW','reason':str(e)}
 if not due:return {**result,'status':'NO SESSION','reason':'No configured trading session for this workflow'}
 normal=[]
 for run in runs:
  # Source-code push runs for the equity study run tests only, never the study.
  if run.get('event') not in ('schedule','workflow_dispatch'):continue
  stamp=datetime.fromisoformat(run['created_at'].replace('Z','+00:00')).astimezone(IST)
  if stamp.date()==now.date():normal.append(run)
 result['runs']=[r['html_url'] for r in normal]
 if not normal:
  if clock<config['ready']:return {**result,'status':'NOT DUE','reason':'Waiting for scheduled start and preparation grace'}
  return {**result,'status':'MISSING','reason':'No current-day scheduled/manual execution; no automatic restart attempted'}
 active=[r for r in normal if r.get('status') in ACTIVE]
 if active:
  state='QUEUED' if all(r.get('status')!='in_progress' for r in active) else 'STALLED' if clock>=config['finish'] else 'RUNNING'
  return {**result,'status':state,'reason':'Queued/waiting needs attention before capture' if state=='QUEUED' else 'Still active beyond expected completion' if state=='STALLED' else 'Execution in progress; completion not yet verified'}
 latest=max(normal,key=lambda r:r['id'])
 if latest.get('conclusion')!='success':return {**result,'status':'FAILED','reason':'Latest execution '+str(latest.get('conclusion')),'run_id':latest['id']}
 if len(normal)>1 and any(r.get('conclusion')!='success' for r in normal):return {**result,'status':'REVIEW','reason':'Mixed current-day outcomes; inspect partial/duplicate runs','run_id':latest['id']}
 return {**result,'status':'SUCCESS','reason':'GitHub execution succeeded; market coverage and published results are not independently validated','run_id':latest['id']}

class Reader:
 def __init__(self,token):
  self.session=requests.Session();self.session.headers.update(Authorization='Bearer '+token,Accept='application/vnd.github+json',**{'X-GitHub-Api-Version':'2022-11-28'})
 def get(self,path,params=None):
  response=self.session.get('https://api.github.com/repos/'+REPO+'/actions/'+path,params=params,timeout=(3,12));response.raise_for_status();return response.json()
 def runs(self,workflow):
  result=[]
  for page in range(1,4):
   rows=self.get('workflows/'+workflow+'/runs',{'branch':'main','per_page':100,'page':page})['workflow_runs'];result.extend(rows)
   if len(rows)<100:return result
  raise RuntimeError('Run pagination incomplete; health cannot be verified')
 def failed_steps(self,run_id):
  jobs=self.get('runs/'+str(run_id)+'/jobs',{'per_page':100})
  return [{'job':j['name'],'conclusion':j.get('conclusion'),'url':j.get('html_url'),'failed_steps':[s['name'] for s in j.get('steps',[]) if s.get('conclusion') in ('failure','cancelled','timed_out')]} for j in jobs['jobs'] if j.get('conclusion') not in ('success','skipped',None)]

def main():
 now=datetime.now(IST);reader=Reader(os.environ['GH_TOKEN']);results=[]
 for workflow in TARGETS:
  try:
   result=evaluate(workflow,reader.runs(workflow),now)
   if result.get('run_id') and result['status'] in ('FAILED','REVIEW'):result['failed_jobs']=reader.failed_steps(result['run_id'])
  except Exception as e:result={'workflow':workflow,'name':TARGETS[workflow]['name'],'status':'ACCESS ERROR','reason':type(e).__name__+'; cannot verify workflow execution'}
  results.append(result)
 report={'checked_at_ist':now.isoformat(),'read_only':True,'results':results};Path('workflow-health.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 lines=['# Additional workflow health','', 'Read-only execution checks. No dispatch, broker calls or Sheet writes.','']
 for r in results:
  lines.append('- **'+r['name']+' — '+r['status']+'**: '+r['reason'])
  lines.extend('  - '+url for url in r.get('runs',[]))
  for j in r.get('failed_jobs',[]):lines.append('  - Failed job '+j['job']+'; steps: '+', '.join(j['failed_steps']))
 text='\n'.join(lines)+'\n';Path('workflow-health.md').write_text(text,encoding='utf-8');print(text)
 if os.getenv('GITHUB_STEP_SUMMARY'):
  with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:f.write(text)
 if any(r['status'] in ALERTS for r in results):sys.exit(1)
if __name__=='__main__':main()

