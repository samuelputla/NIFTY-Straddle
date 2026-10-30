import unittest
from rolling_engine import Study
from measurement_log import delta_rows,execution_rows,EXEC_HEADERS

def pair():return dict(at=0,spot=22950,strike=22950,CE=dict(symbol='CE',price=100,delta=.51),PE=dict(symbol='PE',price=100,delta=-.49))
class Measurements(unittest.TestCase):
 def test_stopped_leg_sample_gap_and_crossing(self):
  s=Study('Delta Based','Monthly','2026-11-23','2026-10-30');s.advance('2026-10-30T09:30:00+05:30',pair(),{}, {},0)
  s.tick('CE',130,'2026-10-30T09:31:00+05:30');sc=s.scenarios[25];self.assertEqual(sc.active.legs['CE'].exit,125)
  s.observe_delta('2026-10-30T09:31:00+05:30',{'CE':.7,'PE':-.3},'2026-10-30T09:31:00+05:30')
  m=sc.active.measurement;self.assertAlmostEqual(m['net'],-.4);self.assertAlmostEqual(m['change'],.38);self.assertEqual(m['count'],1);self.assertEqual(m['cross_at'],'2026-10-30T09:31:00+05:30')
  s.observe_delta('2026-10-30T09:31:02+05:30',{'CE':.7,'PE':-.3},'2026-10-30T09:31:00+05:30');self.assertEqual(m['count'],1)
  s.observe_delta('2026-10-30T09:32:00+05:30',{'CE':.6},'2026-10-30T09:32:00+05:30');self.assertEqual(m['count'],1)
  s.observe_delta('2026-10-30T09:33:00+05:30',{'CE':.5,'PE':-.5},'2026-10-30T09:33:00+05:30');self.assertEqual(m['gap'],120);self.assertAlmostEqual(m['max_change'],.38)
  row=next(r for r in execution_rows([s]) if r[4]==25 and r[6]=='CE');self.assertEqual(row[8:13],[125,130,125,5,325]);self.assertEqual(len(row),len(EXEC_HEADERS))
  s.advance('2026-10-30T15:00:00+05:30',None,{'CE':130,'PE':50},{},0);self.assertEqual(sc.active.close_delta,0);self.assertEqual(sc.active.legs['CE'].exit,125)
 def test_exact_threshold_and_no_history_invention(self):
  s=Study('Delta Based','Current Week','2026-11-03','2026-10-30');s.advance('2026-10-30T09:30:00+05:30',pair(),{},{},0)
  s.observe_delta('2026-10-30T09:31:00+05:30',{'CE':.685,'PE':-.315},'2026-10-30T09:31:00+05:30')
  self.assertNotIn('cross_at',s.scenarios[25].active.measurement)
  self.assertFalse(delta_rows([s])[0][24]);self.assertEqual(len(s.scenarios[25].cycles),1)
if __name__=='__main__':unittest.main()

