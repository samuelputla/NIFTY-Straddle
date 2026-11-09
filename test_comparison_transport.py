"""Retired dashboard has no production publishing paths."""
import unittest
from pathlib import Path
class DisconnectedDashboardTests(unittest.TestCase):
 def test_no_old_dashboard_paths(self):
  for filename in ('comparison_runner.py','rolling_collector.py'):
   source=Path(filename).read_text()
   self.assertNotIn('chatgpt.site',source)
   self.assertNotIn('STRADDLE_DASHBOARD_TOKEN',source)
  for path in Path('.github/workflows').glob('*.yml'):
   self.assertNotIn('STRADDLE_DASHBOARD_TOKEN',path.read_text())
   self.assertNotIn('sync_dashboard.py',path.read_text())
  self.assertFalse(Path('sync_dashboard.py').exists())
  self.assertFalse(Path('.github/workflows/dashboard-sync.yml').exists())
if __name__=='__main__':unittest.main()
