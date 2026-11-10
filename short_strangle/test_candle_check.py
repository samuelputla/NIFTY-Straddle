import unittest
from datetime import datetime
from short_strangle.candle_check import check_leg, apply_check

DAY = '2026-11-09'
ENTRY = DAY+'T14:57:02+05:30'
TS = int(datetime.fromisoformat(DAY+'T14:57:00+05:30').timestamp())
def response(highs=(105,106,107)):
    return {'s':'ok','candles':[[TS+i*60,100,h,90,100,10] for i,h in enumerate(highs)]}
def row():
    r = ['']*28
    r[1],r[10] = DAY,ENTRY
    r[11:17] = ['CE','PE',100,100,110,110]
    r[17:23] = [80,80,DAY+'T15:00:01+05:30',DAY+'T15:00:01+05:30','15:00 EXIT observed paper mark','15:00 EXIT observed paper mark']
    r[26] = 'Original quote gap'
    return r

class CandleTests(unittest.TestCase):
    def test_equal_stop_counts_and_first_crossing(self):
        out = check_leg(response((105,110,120)),ENTRY,110,DAY)
        self.assertEqual(out['state'],'STOP HIT')
        self.assertIn('14:58:00',out['first_confirmed_hit'])
        self.assertEqual(out['high'],120)
        self.assertEqual(out['low'],90)

    def test_entry_minute_crossing_is_ambiguous(self):
        self.assertEqual(check_leg(response((120,105,106)),ENTRY,110,DAY)['state'],'ENTRY MINUTE AMBIGUOUS')
        self.assertEqual(check_leg(response((120,105,106)),DAY+'T14:57:00+05:30',110,DAY)['state'],'STOP HIT')

    def test_no_hit_needs_every_minute_and_excludes_1500(self):
        data = response()
        data['candles'].append([TS+180,100,200,90,100,10])
        self.assertEqual(check_leg(data,ENTRY,110,DAY)['state'],'NO STOP HIT')
        data['candles'].pop(1)
        self.assertEqual(check_leg(data,ENTRY,110,DAY)['state'],'MISSING CANDLES')

    def test_duplicate_or_bad_ohlc_cannot_verify_no_hit(self):
        data = response()
        data['candles'].append(data['candles'][0])
        self.assertFalse(check_leg(data,ENTRY,110,DAY)['complete_minutes'])
        data = response()
        data['candles'][1][3] = 150
        self.assertFalse(check_leg(data,ENTRY,110,DAY)['complete_minutes'])

    def test_corrects_missed_stop_and_keeps_earlier_observed_stop(self):
        r = row()
        out,_ = apply_check(r,{'CE':response((105,112,120)),'PE':response()},DAY)
        self.assertEqual(out[17],110)
        self.assertIn('14:58:00',out[19])
        self.assertEqual(out[18],80)
        self.assertIn('Original quote gap',out[26])
        self.assertEqual(apply_check(out,{'CE':response((105,112,120)),'PE':response()},DAY)[0],out)
        r[17],r[19],r[21] = 110,DAY+'T14:57:30+05:30','SL threshold paper fill'
        out,_ = apply_check(r,{'CE':response((105,112,120))},DAY)
        self.assertEqual(out[19],r[19])

    def test_missing_history_does_not_invent_stop(self):
        r = row()
        out,details = apply_check(r,{},DAY)
        self.assertEqual(out[17:23],r[17:23])
        self.assertEqual(details['CE']['state'],'MISSING CANDLES')

if __name__ == '__main__': unittest.main()
