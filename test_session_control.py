import unittest
from datetime import datetime
from unittest.mock import patch
from session_control import check, relevant, IST

NOW=datetime(2026,11,13,9,12,tzinfo=IST)
class API:
    def __init__(self,runs): self.rows=runs;self.sent=[]
    def runs(self,w): return self.rows
    def dispatch(self,w,i): self.sent.append((w,i))

class ControlTests(unittest.TestCase):
    def runrow(self,**kw):
        return dict(id=1,created_at='2026-11-13T03:30:00Z',event='workflow_dispatch',status='completed',conclusion='failure',html_url='run',**kw)
    def test_failed_today_is_never_blindly_restarted(self):
        api=API([self.runrow()]);self.assertEqual(check(api,'fixed',NOW,lambda *a:False)['status'],'EXISTS');self.assertFalse(api.sent)
    def test_late_start_never_dispatches(self):
        api=API([]);self.assertEqual(check(api,'fixed',NOW.replace(hour=10),lambda *a:False)['status'],'NOT DUE')
    def test_sheet_blocks_missing_run(self):
        self.assertEqual(check(API([]),'rolling',NOW,lambda *a:True)['status'],'SHEET PRESENT; NO RESTART')
    def test_code_tests_do_not_block(self):
        row=self.runrow();row['event']='push'
        self.assertEqual(check(API([row]),'fixed',NOW,lambda *a:False,True)['status'],'WOULD DISPATCH')
    def test_old_active_run_blocks(self):
        row=self.runrow();row.update(created_at='2026-11-12T03:00:00Z',status='queued')
        self.assertTrue(relevant('fixed',row,NOW))
    def test_collect_does_not_block_close_check(self):
        row=self.runrow(display_title='Short Strangle collect')
        self.assertFalse(relevant('close',row,NOW.replace(hour=15,minute=10)))
    def test_dispatch_and_dry_run(self):
        api=API([])
        with patch('session_control.datetime') as clock:
            clock.now.return_value=NOW
            self.assertIn('ACCEPTED',check(api,'fixed',NOW,lambda *a:False)['status'])
        self.assertEqual(len(api.sent),1)
        api=API([]);check(api,'fixed',NOW,lambda *a:False,True);self.assertEqual(api.sent,[])

