import copy
import re
import unittest
from short_term_calls.storage import Store,SCHEMAS,CALLS,EVENTS
from short_term_calls.engine import replay
from test_engine import plan,valid_rows


class Sheet:
    def __init__(self,title):self.title=title


class Book:
    def __init__(self):self.rows={n:[list(h)] for n,h in SCHEMAS.items()}
    def worksheets(self):return [Sheet(n) for n in self.rows]
    def values_batch_get(self,ranges,params=None):
        return {'valueRanges':[{'values':copy.deepcopy(self.rows[r.split("'")[1]])} for r in ranges]}
    def values_batch_update(self,body):
        assert body['valueInputOption']=='RAW'
        for change in body['data']:
            title=change['range'].split("'")[1]
            index=int(re.search(r'!A(\d+)',change['range']).group(1))-1
            while len(self.rows[title])<=index:self.rows[title].append([])
            self.rows[title][index]=copy.deepcopy(change['values'][0])


class StorageTests(unittest.TestCase):
    def test_retry_registration_does_not_duplicate(self):
        book=Book();store=Store(book);p=plan()
        store.register(p,p['issued_at']);store.register(p,p['issued_at'])
        self.assertEqual(len(book.rows[CALLS]),2)
        self.assertEqual(Store(book).plans(),[p])

    def test_frozen_plan_cannot_change(self):
        store=Store(Book());p=plan();store.register(p,p['issued_at'])
        with self.assertRaises(ValueError):store.register(dict(p,target_2=121),p['issued_at'])

    def test_late_registration_refused(self):
        with self.assertRaises(ValueError):Store(Book()).register(plan(),'2026-11-09T09:16:00+05:30')

    def test_replay_log_idempotent_after_restart(self):
        p=plan();book=Book();store=Store(book);store.register(p,p['issued_at'])
        result=replay(p,valid_rows(),'2026-11-09T10:15:00+05:30')
        store.save_result(p,result);count=len(book.rows[EVENTS])
        Store(book).save_result(p,result)
        self.assertEqual(count,len(book.rows[EVENTS]))

    def test_manual_visible_plan_edit_detected(self):
        p=plan();book=Book();Store(book).register(p,p['issued_at']);book.rows[CALLS][1][8]=999
        with self.assertRaises(ValueError):Store(book).plans()

    def test_provider_event_revision_refused(self):
        p=plan();store=Store(Book());store.register(p,p['issued_at'])
        result=replay(p,valid_rows(),'2026-11-09T10:15:00+05:30');store.save_result(p,result)
        altered=copy.deepcopy(result);altered['events'][0]['price']='999'
        with self.assertRaises(ValueError):store.save_result(p,altered)


if __name__=='__main__':unittest.main()
