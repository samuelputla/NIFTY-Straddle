import json
import tempfile
import types
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import Mock,patch

from short_strangle.startup import capture_spot,checked_response,reserved_session,MarketDataError,INDEX
from short_strangle.storage import Store
from short_strangle.test_storage import Book
from short_strangle.test_rules import sample


class Clock:
    def __init__(self, clock='09:30:00'):
        self.value=datetime.fromisoformat('2026-11-23T'+clock+'+05:30')
    def now(self): return self.value
    def sleep(self,seconds): self.value+=timedelta(seconds=seconds)


def quote(value=25700):
    return {'s':'ok','d':[{'n':INDEX,'s':'ok','v':{'lp':value}}]}


class StartupTests(unittest.TestCase):
    def test_collector_initial_spot_failure_closes_socket_and_marks_reservation(self):
        from short_strangle import collector
        book=Book(); store=Store(book,'2026-11-23')
        socket=Mock()
        def socket_factory(**kwargs):
            socket.connect.side_effect=kwargs['on_connect']
            return socket
        model=Mock()
        model.optionchain.return_value={'s':'ok','data':{'expiryData':[]}}
        fyers=types.ModuleType('fyers_apiv3');fyers.fyersModel=Mock(FyersModel=Mock(return_value=model))
        websocket=types.ModuleType('fyers_apiv3.FyersWebsocket')
        websocket.data_ws=Mock(FyersDataSocket=Mock(side_effect=socket_factory))
        gspread=types.ModuleType('gspread');gspread.authorize=Mock()
        service_account=types.ModuleType('google.oauth2.service_account');service_account.Credentials=Mock()
        resilience=types.ModuleType('sheets_resilience');resilience.ResilientHTTPClient=Mock()
        modules={'fyers_apiv3':fyers,'fyers_apiv3.FyersWebsocket':websocket,'gspread':gspread,
                 'google.oauth2.service_account':service_account,'sheets_resilience':resilience}
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=b''
        with tempfile.TemporaryDirectory() as tmp, patch.dict('sys.modules',modules), \
                patch.dict('os.environ',{'GITHUB_RUN_ID':'test','FYERS_ACCESS_TOKEN':'test','GOOGLE_SERVICE_ACCOUNT_JSON':'{}'}), \
                patch.object(collector,'OUT',Path(tmp)),patch.object(collector,'now',Clock().now), \
                patch('short_strangle.storage.Store',return_value=store),patch.object(collector,'Observer'), \
                patch.object(collector.urllib.request,'urlopen',return_value=response), \
                patch.object(collector,'select_expiries',return_value={}), \
                patch.object(collector,'capture_spot',side_effect=MarketDataError('FYERS quotes failed (code -99)')), \
                patch.object(Path,'replace',side_effect=OSError('snapshot disk failure')):
            with self.assertRaises(MarketDataError): collector.main()
            socket.close_connection.assert_called_once()
            self.assertTrue((Path(tmp)/'failure.json').exists())
        self.assertTrue(all(r[25]=='INCOMPLETE' for r in book.calls[-1]['data'][1]['values']))

    def test_transient_provider_error_recovers_inside_window(self):
        clock=Clock()
        call=Mock(side_effect=[MarketDataError('FYERS quotes failed (code -99)'),quote()])
        value,at=capture_spot(call,lambda:None,clock.now,clock.sleep)
        self.assertEqual(value,25700)
        self.assertEqual(at[11:19],'09:30:01')
        self.assertEqual(call.call_count,2)

    def test_stream_can_recover_rest_failure(self):
        clock=Clock()
        fresh=Mock(side_effect=[None,25701])
        call=Mock(side_effect=ConnectionError('private provider details'))
        value,_=capture_spot(call,fresh,clock.now,clock.sleep)
        self.assertEqual(value,25701)
        self.assertEqual(call.call_count,1)

    def test_no_pre_entry_spot_or_late_request(self):
        clock=Clock('09:29:59')
        call=Mock(return_value=quote())
        _,at=capture_spot(call,lambda:None,clock.now,clock.sleep)
        self.assertEqual(at[11:19],'09:30:00')
        late=Clock('09:30:20')
        with self.assertRaisesRegex(RuntimeError,'Missed spot'):
            capture_spot(call,lambda:25700,late.now,late.sleep)
        self.assertEqual(call.call_count,1)

    def test_repeated_errors_end_at_deadline(self):
        clock=Clock(); call=Mock(side_effect=TimeoutError())
        with self.assertRaisesRegex(RuntimeError,'Missed spot'):
            capture_spot(call,lambda:None,clock.now,clock.sleep)
        self.assertEqual(clock.now().strftime('%H:%M:%S'),'09:30:20')
        self.assertEqual(call.call_count,20)

    def test_response_after_deadline_is_rejected(self):
        clock=Clock('09:30:19')
        def slow(*args):
            clock.sleep(2)
            return quote()
        with patch('short_strangle.startup.run_with_timeout',side_effect=lambda f,t:f()) as bounded:
            with self.assertRaisesRegex(RuntimeError,'Missed spot'):
                capture_spot(slow,lambda:None,clock.now,clock.sleep)
        self.assertEqual(bounded.call_args.args[1],1)

    def test_error_logs_only_method_and_numeric_code(self):
        with self.assertRaisesRegex(MarketDataError,r'FYERS quotes failed \(code -16\)') as caught:
            checked_response('quotes',{'s':'error','code':-16,'message':'SECRET'})
        self.assertNotIn('SECRET',str(caught.exception))
        with self.assertRaises(MarketDataError): checked_response('quotes',None)

    def test_failed_startup_updates_same_reserved_rows(self):
        book=Book(); store=Store(book,'2026-11-23');store.reserve()
        original=[d['range'] for d in book.calls[-1]['data']]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MarketDataError):
                with reserved_session(store,Path(tmp)):
                    raise MarketDataError('FYERS quotes failed (code -99)')
            self.assertIn('code -99',json.loads((Path(tmp)/'failure.json').read_text())['error'])
        result=book.calls[-1]['data']
        self.assertEqual([d['range'] for d in result],original)
        self.assertEqual(len(result[0]['values']),9)
        self.assertEqual(len(result[1]['values']),81)
        self.assertTrue(all(r[4]=='INCOMPLETE' for r in result[0]['values']))
        self.assertTrue(all(r[25]=='INCOMPLETE' and r[13]=='' for r in result[1]['values']))

    def test_failure_does_not_replace_saved_trade_prices(self):
        book=Book();store=Store(book,'2026-11-23');store.save(sample())
        count=len(book.calls)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                with reserved_session(store,Path(tmp)): raise RuntimeError('failed')
        self.assertEqual(len(book.calls),count)


if __name__=='__main__': unittest.main()
