import unittest
from datetime import datetime
from short_strangle.close_session import candle_mark, reconcile

def row():
    r = ['']*28
    r[1] = '2026-11-09'
    r[10] = '2026-11-09T09:30:02+05:30'
    r[11:15] = ['CE','PE',100,100]
    r[24:28] = [150,'INCOMPLETE','Quote gap',65]
    return r

class CloseTests(unittest.TestCase):
    def test_preserves_stop_and_recovers_only_missing_exit(self):
        r = row()
        r[17],r[19],r[21] = 110,'2026-11-09T10:00:00+05:30','SL threshold paper fill'
        out = reconcile(r,{'CE':1,'PE':80},'2026-11-09')
        self.assertEqual(out[17],110)
        self.assertEqual(out[18],80)
        self.assertEqual(out[23],500)
        self.assertEqual(out[25],'COMPLETED')
        self.assertIn('Quote gap',out[26])
        self.assertIn('proxy',out[22])
        self.assertEqual(reconcile(out,{'CE':2,'PE':2},'2026-11-09'),out)

    def test_missing_and_partial_exits_stay_incomplete(self):
        r = row()
        r[17] = 90
        out = reconcile(r,{'CE':1},'2026-11-09')
        self.assertEqual(out[17],90)
        self.assertEqual(out[23],'')
        self.assertEqual(out[25],'INCOMPLETE')

    def test_exact_1500_minute_open_only(self):
        ts = int(datetime.fromisoformat('2026-11-09T15:00:00+05:30').timestamp())
        bar = [ts,20,24,18,21,100]
        self.assertEqual(candle_mark({'s':'ok','candles':[bar]},'2026-11-09'),20)
        self.assertIsNone(candle_mark({'s':'ok','candles':[[ts-60,20,24,18,21,100]]},'2026-11-09'))
        self.assertIsNone(candle_mark({'s':'error','candles':[bar]},'2026-11-09'))

if __name__ == '__main__': unittest.main()
