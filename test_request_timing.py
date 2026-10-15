import ast
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from request_timing import await_request, run_with_timeout, start_request, collect_ready_requests


def load_function(name, env):
    tree = ast.parse(Path('today_test.py').read_text(encoding='utf-8'))
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[func], type_ignores=[]), 'today_test.py', 'exec'), env)
    return env[name]


class TimingRegressionTests(unittest.TestCase):
    def test_pending_metadata_does_not_wait_and_can_expire(self):
        unfinished = {'VIX': (threading.Event(), {})}
        started = time.monotonic()
        self.assertEqual(collect_ready_requests(unfinished), {})
        self.assertLess(time.monotonic()-started, .1)
        self.assertIn('VIX', unfinished)
        expired = collect_ready_requests(unfinished, expired=True)
        self.assertIsInstance(expired['VIX'][1], TimeoutError)
        self.assertEqual(unfinished, {})

    def test_stop_triggers_while_metadata_and_sheet_writes_are_pending(self):
        now=datetime(2026,10,15,9,30,1)
        scenario={'ce_hit':False}
        env={'now_ist':lambda:now,'target_end':now+timedelta(hours=5),
             'stop_event':threading.Event(),'state_lock':threading.RLock(),
             'ce_sl_values':[110],'pe_sl_values':[110],'SL_PERCENTAGES':[10],
             'pending_scenario_updates':set(),
             'state':{'ce_ltp':100,'ce_high':100,'ce_low':100,'scenarios':{10:scenario}}}
        load_function('update_summary_after_event',env)
        load_function('handle_sl',env)('CE',115)
        self.assertTrue(scenario['ce_hit'])
        self.assertEqual(scenario['ce_exit'],110)
        self.assertEqual(env['pending_scenario_updates'],{10})

    def test_delayed_metadata_keeps_original_entries_and_actual_retrieval_time(self):
        retrieved=datetime(2026,10,15,9,30,2)
        applied=datetime(2026,10,15,9,30,8)
        done=threading.Event();done.set()
        env={'collect_ready_requests':collect_ready_requests,'time_module':time,
             'metadata_deadline':time.monotonic()+15,
             'metadata_requests':{'VIX':(done,{'value':({'VIX':{'lp':14.9}},retrieved)}),
                                  'OI':(done,{'value':({'s':'ok','data':{'callOi':100,'putOi':120}},retrieved)})},
             'VIX_SYMBOL':'VIX','india_vix':None,'vix_retrieved_at':None,
             'vix_snapshot_status':'PENDING','call_oi':50,'put_oi':50,'pcr':1,
             'market_bias':'Neutral','oi_retrieved_at':None,'oi_snapshot_status':'PRE-ENTRY',
             'ce_entry':100,'pe_entry':110,'capture_time':retrieved-timedelta(seconds=2),
             'ce_sl_values':[110],'pe_sl_values':[121],
             'now_ist':lambda:applied,'fmt_time':lambda x:x.strftime('%H:%M:%S')}
        load_function('ltp_from_quote',env);load_function('daily_bias',env)
        self.assertTrue(load_function('poll_entry_metadata',env)())
        self.assertEqual(env['vix_retrieved_at'],retrieved)
        self.assertEqual(env['oi_retrieved_at'],retrieved)
        self.assertEqual((env['ce_entry'],env['pe_entry']),(100,110))
        self.assertEqual(env['ce_sl_values'],[110])
        self.assertEqual(env['pcr'],1.2)

    def test_monitor_start_precedes_initial_sheet_writes(self):
        source=Path('today_test.py').read_text(encoding='utf-8')
        launch=source.index('name="fyers-websocket-connect"')
        self.assertLess(launch,source.index('scenario_first_row = append_scenario_rows'))
        self.assertNotIn('await_request(',source)

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

