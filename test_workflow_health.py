import unittest
from datetime import datetime
from workflow_health import evaluate,IST
DAY='2026-11-06'
def at(clock,day=DAY):return datetime.fromisoformat(day+'T'+clock+'+05:30')
def run(status='completed',conclusion='success',event='schedule',day=DAY,id=1):return {'id':id,'status':status,'conclusion':conclusion,'event':event,'created_at':day+'T03:40:00Z','html_url':'https://github.com/fixture/run/'+str(id)}
class HealthTests(unittest.TestCase):
 def test_equity_not_due_in_morning(self):self.assertEqual(evaluate('nifty-study.yml',[],at('09:20:00'))['status'],'NOT DUE')
 def test_missing_after_grace(self):
  for w,t in [('short-strangle.yml','09:20:00'),('nifty-study.yml','17:20:00')]:self.assertEqual(evaluate(w,[],at(t))['status'],'MISSING')
 def test_push_tests_not_counted_as_study(self):self.assertEqual(evaluate('nifty-study.yml',[run(event='push')],at('17:20:00'))['status'],'MISSING')
 def test_success_failure_queued_and_stalled(self):
  for r,state in [(run(),'SUCCESS'),(run(conclusion='failure'),'FAILED'),(run('queued',None),'QUEUED'),(run('in_progress',None),'STALLED')]:self.assertEqual(evaluate('nifty-study.yml',[r],at('17:20:00'))['status'],state)
 def test_live_strangle_not_failed_before_finish(self):self.assertEqual(evaluate('short-strangle.yml',[run('in_progress',None)],at('09:20:00'))['status'],'RUNNING')
 def test_old_success_does_not_cover_today(self):self.assertEqual(evaluate('nifty-study.yml',[run(day='2026-11-05')],at('17:20:00'))['status'],'MISSING')
 def test_mixed_runs_require_review(self):self.assertEqual(evaluate('nifty-study.yml',[run(conclusion='failure'),run(id=2)],at('17:20:00'))['status'],'REVIEW')
 def test_distinct_calendars_and_unknown_year(self):
  self.assertEqual(evaluate('short-strangle.yml',[],at('17:20:00','2026-11-08'))['status'],'NO SESSION')
  self.assertEqual(evaluate('nifty-study.yml',[],at('17:20:00','2026-11-08'))['status'],'MISSING')
  self.assertEqual(evaluate('nifty-study.yml',[],at('17:20:00','2027-01-04'))['status'],'REVIEW')
if __name__=='__main__':unittest.main()

