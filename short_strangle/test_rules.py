import unittest
from dataclasses import asdict
from short_strangle.engine import *
from short_strangle.report import audit

def sample():
    contracts = {'2026-11-09': {(k,s):f'{k}{s}' for k in range(24000, 26001, 100) for s in ('CE','PE')}}
    return make_scenarios('2026-11-09', 25000, '2026-11-09T09:30:01+05:30', dict.fromkeys(CHOICES, '2026-11-09'), contracts)

class Rules(unittest.TestCase):
    def test_report_rejects_duplicate_and_bad_stop(self):
        scenarios = sample()
        self.assertEqual(audit({'scenarios':[asdict(s) for s in scenarios]})['scenarios'],81)
        with self.assertRaises(ValueError): audit({'scenarios':[asdict(scenarios[0])]*81})
        s = scenarios[0]
        s.enter(dict.fromkeys(s.symbols.values(),100),'2026-11-09T09:30:02+05:30')
        s.exits['CE'] = (120,'2026-11-09T10:00:00+05:30','SL threshold paper fill')
        with self.assertRaises(ValueError): audit({'scenarios':[asdict(s) for s in scenarios]})

    def test_rounding_half_up_and_spot_basis(self):
        self.assertEqual(strikes(25000,1), (25300,24800))
        self.assertEqual(strikes(25000,1.5), (25400,24600))
        self.assertEqual(strikes(25000,2), (25500,24500))
        self.assertEqual(strikes(25123,1), (25400,24900))

    def test_all_81_and_schemas(self):
        scenarios = sample()
        self.assertEqual(len(scenarios), 81)
        self.assertEqual(len({s.row()[0] for s in scenarios}), 81)
        self.assertTrue(all(len(s.row()) == len(HEADERS) for s in scenarios))
        self.assertEqual(len(summary_rows(scenarios)),9)
        self.assertTrue(all(len(r)==len(SUMMARY_HEADERS) for r in summary_rows(scenarios)))

    def test_independent_stops_and_no_reentry(self):
        a,b = sample()[:2]
        for s in (a,b): s.enter(dict.fromkeys(s.symbols.values(),100), '2026-11-09T09:30:02+05:30')
        for s in (a,b): s.tick(s.symbols['CE'],112,'2026-11-09T10:00:00+05:30')
        self.assertIn('CE',a.exits)
        self.assertNotIn('CE',b.exits)
        a.enter(dict.fromkeys(a.symbols.values(),200), '2026-11-09T11:00:00+05:30')
        self.assertEqual(a.entries['CE'],100)
        a.finish(dict.fromkeys(a.symbols.values(),50),'2026-11-09T15:00:01+05:30')
        self.assertEqual(a.exits['CE'][0],110)
        self.assertEqual(a.net,2450)

    def test_missing_entry_and_final_never_zero(self):
        s = sample()[0]
        s.enter({}, '2026-11-09T09:30:31+05:30')
        s.enter(dict.fromkeys(s.symbols.values(),100),'2026-11-09T09:30:32+05:30')
        self.assertEqual(s.status,'MISSED ENTRY')
        self.assertEqual(s.net,'')
        s = sample()[0]
        s.enter(dict.fromkeys(s.symbols.values(),100),'2026-11-09T09:30:02+05:30')
        s.finish({},'2026-11-09T15:00:01+05:30')
        self.assertEqual(s.status,'INCOMPLETE')
        self.assertEqual(s.net,'')

    def test_exit_boundary_and_no_overwrite(self):
        s = sample()[0]
        s.enter(dict.fromkeys(s.symbols.values(),100),'2026-11-09T09:30:02+05:30')
        s.tick(s.symbols['CE'],200,'2026-11-09T15:00:00+05:30')
        self.assertEqual(s.exits,{})
        s.finish(dict.fromkeys(s.symbols.values(),90),'2026-11-09T15:00:01+05:30')
        s.finish(dict.fromkeys(s.symbols.values(),20),'2026-11-09T15:00:02+05:30')
        self.assertEqual(s.exits['CE'][0],90)

    def test_expiry_cross_verification(self):
        self.assertEqual(select_expiries({'2026-11-09':{},'2026-11-16':{},'2026-11-30':{}}, {'2026-11-30'}, ['2026-11-09','2026-11-16','2026-11-30'])['Monthly'],'2026-11-30')
        with self.assertRaises(RuntimeError): select_expiries({'2026-11-09':{}},set(),['2026-11-09'])

if __name__ == '__main__': unittest.main()
