import unittest
from vix_snapshot import capture_vix, SYMBOL

class VixTests(unittest.TestCase):
    def test_transient_failure_recovers(self):
        calls = []
        def call(*args):
            calls.append(args)
            if len(calls) == 1: raise RuntimeError('transient')
            return {'s':'ok','d':[{'n':SYMBOL,'v':{'lp':17.02}}]}
        result = capture_vix(call, sleep=lambda _: None)
        self.assertEqual(result['value'],17.02)
        self.assertEqual(result['attempts'],2)

    def test_missing_quote_is_bounded_and_not_zero(self):
        calls = []
        def call(*args):
            calls.append(args)
            return {'s':'ok','d':[]}
        result = capture_vix(call, sleep=lambda _: None)
        self.assertNotIn('value',result)
        self.assertEqual(len(calls),3)

