import ast
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from request_timing import await_request, run_with_timeout, start_request


def load_function(name, env):
    tree = ast.parse(Path('today_test.py').read_text(encoding='utf-8'))
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[func], type_ignores=[]), 'today_test.py', 'exec'), env)
    return env[name]


class TimingRegressionTests(unittest.TestCase):
    def test_fast_request_returns_and_errors_propagate(self):
        self.assertEqual(run_with_timeout(lambda: 12, 1), 12)
        def fail():
            raise ValueError('unavailable')
        with self.assertRaises(ValueError):
            run_with_timeout(fail, 1)

    def test_hung_metadata_does_not_prevent_process_exit(self):
        code = 'from request_timing import start_request, await_request; import time; p=start_request(time.sleep,60)\ntry: await_request(p,0.02)\nexcept TimeoutError: pass'
        started=time.monotonic()
        r=subprocess.run([sys.executable,'-c',code],timeout=3,capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertLess(time.monotonic()-started,3)

    def test_nifty_spot_bypasses_problem_quotes_endpoint(self):
        env={'NIFTY_SYMBOL':'NIFTY','get_optionchain_spot_quote':lambda:{'NIFTY':{'lp':22500}},
             'call_fyers':lambda *args:self.fail('Spot must not call quotes')}
        quote=load_function('get_quotes',env)
        self.assertEqual(quote(['NIFTY'])['NIFTY']['lp'],22500)

    def test_invalid_premiums_are_not_accepted(self):
        price=load_function('ltp_from_quote',{})
        for val in [0,-1,float('nan'),float('inf'),None]:
            with self.assertRaises(RuntimeError):price({'lp':val},'CE')
        self.assertEqual(price({'lp':100},'CE'),100)

    def test_tick_at_daily_close_cannot_update_scenarios(self):
        now=datetime(2026,10,14,15,0)
        env={'now_ist':lambda:now,'target_end':now,'stop_event':threading.Event(),
             'state_lock':threading.Lock(),'ce_sl_values':[110],'pe_sl_values':[110],
             'state':{'ce_ltp':100},'SL_PERCENTAGES':[10]}
        load_function('handle_sl',env)('CE',150)
        self.assertEqual(env['state'],{'ce_ltp':100})


if __name__=='__main__':unittest.main()
