import copy
import unittest
from fixed_sheet_store import ScopedWorksheet, appended_row, reserve_daily, select_choice

class FakeSpreadsheet:
    def __init__(self, sheet):
        self.sheet = sheet
        self.before_append = None

    def batch_update(self, body):
        if self.before_append:
            self.sheet.rows.append(self.before_append)
            self.before_append = None
        request = body['requests'][0]['appendCells']
        self.sheet.rows.extend([
            [next(iter(cell['userEnteredValue'].values())) for cell in row['values']]
            for row in request['rows']
        ])

class Sheet:
    def __init__(self):
        self.rows = [['Date', 'Run Status', 'Expiry Choice']]
        self.id = 1
        self.title = 'Summary'
        self.spreadsheet = FakeSpreadsheet(self)
    def get_all_values(self, **kwargs):
        return copy.deepcopy(self.rows)
    def update(self, range_name, values, **kwargs):
        first = int(range_name[1:]) - 1
        self.rows[first:first + len(values)] = copy.deepcopy(values)
    def batch_update(self, updates, **kwargs):
        for item in updates:
            self.update(item['range'], item['values'])

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.raw = Sheet()
        self.headers = ['Date', 'Run Status']
        self.a = ScopedWorksheet(self.raw, self.headers, 'Current Week')
        self.b = ScopedWorksheet(self.raw, self.headers, 'Monthly')
    def test_interleaved_jobs_do_not_overwrite_other_expiry(self):
        a = reserve_daily(self.a, '2026-11-10', self.headers)
        b = reserve_daily(self.b, '2026-11-10', self.headers)
        self.assertEqual((a, b), (2, 3))
        self.b.update('A3:B3', [['2026-11-10', 'MONTHLY']])
        self.a.update('A2:B2', [['2026-11-10', 'CURRENT']])
        self.assertEqual(self.raw.rows[1:], [['2026-11-10','CURRENT','Current Week'], ['2026-11-10','MONTHLY','Monthly']])
        self.assertEqual(self.b.get_all_values(), [self.headers, [], ['2026-11-10','MONTHLY']])
    def test_duplicate_scoped_to_date_and_expiry(self):
        reserve_daily(self.a, '2026-11-10', self.headers)
        with self.assertRaises(RuntimeError):
            reserve_daily(self.a, '2026-11-10', self.headers)
        self.assertEqual(reserve_daily(self.b, '2026-11-10', self.headers), 3)
    def test_unowned_row_cannot_be_overwritten(self):
        reserve_daily(self.a, '2026-11-10', self.headers)
        with self.assertRaises(RuntimeError):
            self.b.update('A2:B2', [['2026-11-10', 'CORRUPT']])
    def test_multirow_append_uses_server_range(self):
        self.b.append_row(['2026-11-10', 'MONTHLY'])
        first = appended_row(self.a.append_rows([['2026-11-10','10%'], ['2026-11-10','15%']]))
        self.assertEqual(first, 3)
        self.a.batch_update([{'range':'A4:B4','values':[['2026-11-10','UPDATED']]}])
        self.assertEqual(self.raw.rows[1][-1], 'Monthly')
        self.assertEqual(self.raw.rows[3], ['2026-11-10','UPDATED','Current Week'])
    def test_parallel_append_resolves_own_rows_after_another_writer(self):
        self.raw.spreadsheet.before_append = ['2026-11-10', 'OTHER', 'Next Week']
        row = appended_row(self.a.append_row(['2026-11-10', 'CURRENT']))
        self.assertEqual(row, 3)
        self.a.update('A3:B3', [['2026-11-10', 'UPDATED']])
        self.assertEqual(self.raw.rows[1][-1], 'Next Week')

    def test_unknown_append_outcome_fails_closed(self):
        with self.assertRaises(RuntimeError):
            appended_row({})
    def test_choice_filter_preserves_original_columns(self):
        self.a.append_row(['2026-11-10', 'A'])
        self.b.append_row(['2026-11-10', 'B'])
        self.assertEqual(select_choice(self.raw.rows,'Monthly'), [self.headers,['2026-11-10','B']])
    def test_schema_mismatch_fails_before_write(self):
        self.raw.rows[0][-1] = 'Wrong'
        with self.assertRaises(RuntimeError):
            reserve_daily(self.a, '2026-11-10', self.headers)
        self.assertEqual(len(self.raw.rows), 1)

if __name__ == '__main__':
    unittest.main()
