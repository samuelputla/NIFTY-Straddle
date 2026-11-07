import unittest

from rolling_collector import fresh_prices
from rolling_engine import Cycle, Leg, Study


class AuditRegressionTests(unittest.TestCase):
 def settled_study(self):
  study=Study('Time Based','Next Week','2026-11-12','2026-11-06')
  for scenario in study.scenarios.values():
   scenario.done=True
   scenario.cycles.append(Cycle(1,26000,'2026-11-06T09:30:00+05:30',26000,None,{
    'CE':Leg('CE',100,110,90,'2026-11-06T15:00:00+05:30','15:00 EXIT'),
    'PE':Leg('PE',100,110,95,'2026-11-06T15:00:00+05:30','15:00 EXIT'),
   },close_at='2026-11-06T15:00:00+05:30'))
  return study

 def test_quality_warning_does_not_make_settled_session_incomplete(self):
  study=self.settled_study();study.issue('Chain snapshot unavailable')
  self.assertEqual(study.summary('2026-11-06T15:00:01+05:30')[7],'COMPLETED')
  self.assertIn('Chain snapshot unavailable',study.summary('2026-11-06T15:00:01+05:30')[9])

 def test_unsettled_session_remains_incomplete(self):
  study=self.settled_study()
  study.scenarios[10].cycles[0].legs['CE'].exit=None
  self.assertEqual(study.summary('2026-11-06T15:00:01+05:30')[7],'INCOMPLETE')

 def test_quote_is_never_attributed_to_next_minute(self):
  prices={'CE':(100.0,9.0,'2026-11-06T13:09:59+05:30'),'PE':(95.0,9.5,'2026-11-06T13:10:01+05:30')}
  self.assertEqual(fresh_prices(prices,10.0,'2026-11-06T13:10:02+05:30'),{'PE':95.0})


if __name__=='__main__':
 unittest.main()
