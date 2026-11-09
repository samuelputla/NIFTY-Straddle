import copy
import unittest
from rolling_engine import Study, CHOICES
from rolling_sheet_store import ConsolidatedRollingStore, SCHEMAS, select_study
from fixed_sheet_store import read_studies


class Book:
    def __init__(self):
        self.rows = {n: [h] for n, h in SCHEMAS.items()}
        self.calls = []
        self.fail = False

    def values_batch_get(self, ranges):
        return {'valueRanges': [{'values': copy.deepcopy(v)} for v in self.rows.values()]}

    def values_batch_update(self, body):
        self.calls.append(copy.deepcopy(body))
        if self.fail:
            self.fail = False
            raise TimeoutError('uncertain response')


class Tests(unittest.TestCase):
    def test_same_date_all_expiries_remain_separate_on_retry_and_update(self):
        book = Book()
        store = ConsolidatedRollingStore(book)
        studies = [Study(f, c, '2026-11-23', '2026-11-09')
                   for f in ('Time Based', 'Delta Based') for c in CHOICES]
        summaries = [(f'{s.family} - {s.choice}', s.summary('2026-11-09T15:00:00+05:30')) for s in studies]
        book.fail = True
        with self.assertRaises(TimeoutError):
            store.checkpoint(summaries, [])
        first = book.calls[-1]
        store.checkpoint(summaries, [])
        self.assertEqual(first, book.calls[-1])
        for family in ('Time Based', 'Delta Based'):
            rows = store.cache.snapshot(family + ' Summary')
            self.assertEqual(len(rows), 4)
            self.assertEqual({r[2] for r in rows[1:]}, set(CHOICES))
            self.assertEqual(len({u['range'] for u in first['data'] if family in u['range']}), 3)
        summaries[0][1][7] = 'UPDATED'
        store.checkpoint(summaries, [])
        self.assertEqual(store.cache.snapshot('Time Based Summary')[1][7], 'UPDATED')
        self.assertNotEqual(store.cache.snapshot('Time Based Summary')[2][7], 'UPDATED')
        with self.assertRaises(RuntimeError):
            store.check_day('2026-11-09')

    def test_log_update_keeps_event_row_and_rejects_wrong_target(self):
        book = Book()
        store = ConsolidatedRollingStore(book)
        h = SCHEMAS['Delta Based Logs']
        row = [''] * len(h)
        row[:7] = ['2026-11-09|Delta Based|Monthly|25|1', '2026-11-09', 'Delta Based', 'Monthly', 25, 1, '2026-11-23']
        store.checkpoint([], [('Delta Based - Monthly Logs', [row])])
        first_range = book.calls[-1]['data'][0]['range']
        row[23] = 123
        store.checkpoint([], [('Delta Based - Monthly Logs', [row])])
        self.assertEqual(first_range, book.calls[-1]['data'][0]['range'])
        self.assertEqual(len(store.cache.snapshot('Delta Based Logs')), 2)
        with self.assertRaises(RuntimeError):
            store.checkpoint([], [('Delta Based - Next Week Logs', [row])])

    def test_reports_filter_expiry_without_truncating_columns(self):
        class Sheet:
            def __init__(self, rows): self.rows = rows
            def get_all_values(self): return self.rows
        book = Book()
        h = SCHEMAS['Time Based Summary']
        rows = [h]
        for choice in CHOICES:
            row = [''] * len(h)
            row[:4] = ['2026-11-09', 'Time Based', choice, '2026-11-23']
            rows.append(row)
        book.rows['Time Based Summary'] = rows
        book.rows['Straddle Fixed Summary'] = [['Date', 'Expiry Choice']]
        book.rows['Straddle Fixed Logs'] = [['Event ID', 'Expiry Choice']]
        book.worksheet = lambda n: Sheet(book.rows[n])
        summaries, logs = read_studies(book, ['Time Based - Monthly'])
        selected = summaries['Time Based - Monthly']
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[1][2], 'Monthly')
        self.assertEqual(len(selected[1]), len(h))
        self.assertEqual(logs['Time Based - Monthly'], [SCHEMAS['Time Based Logs']])


if __name__ == '__main__':
    unittest.main()
