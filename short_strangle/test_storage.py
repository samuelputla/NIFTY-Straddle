import unittest
from short_strangle.storage import Store
from short_strangle.engine import SUMMARY, LOGS, HEADERS, SUMMARY_HEADERS
from short_strangle.test_rules import sample

class Tab:
    def __init__(self, title): self.title, self.row_count = title, 1000
    def resize(self, rows): self.row_count = rows

class Book:
    def __init__(self):
        self.calls = []
        self.values = [[SUMMARY_HEADERS], [HEADERS]]
        self.fail = False
    def worksheets(self): return [Tab(SUMMARY),Tab(LOGS)]
    def values_batch_get(self, ranges): return {'valueRanges':[{'values':v} for v in self.values]}
    def values_batch_update(self, data):
        self.calls.append(data)
        if self.fail: raise TimeoutError('Uncertain response')

class StorageTests(unittest.TestCase):
    def test_all_scenarios_in_single_request_and_fixed_retries(self):
        book = Book()
        store = Store(book,'2026-11-09')
        store.reserve()
        self.assertEqual([len(d['values']) for d in book.calls[-1]['data']],[9,81])
        book.fail = True
        with self.assertRaises(TimeoutError): store.save(sample())
        first = book.calls[-1]
        book.fail = False
        store.save(sample())
        self.assertEqual(first, book.calls[-1])
        self.assertEqual(len(book.calls[-1]['data']),2)

    def test_duplicate_day_refused_even_partial_reservation(self):
        book = Book()
        book.values[1].append(['id','2026-11-09'])
        with self.assertRaises(RuntimeError): Store(book,'2026-11-09')

    def test_schema_mismatch_refused(self):
        book = Book()
        book.values[0] = [['wrong']]
        with self.assertRaises(RuntimeError): Store(book,'2026-11-09')

if __name__ == '__main__': unittest.main()
