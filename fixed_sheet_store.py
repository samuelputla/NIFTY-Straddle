"""Shared fixed-entry tabs: expiry isolation and server-allocated append ranges."""
import re

SUMMARY = 'Straddle Fixed Summary'
LOGS = 'Straddle Fixed Logs'
CHOICES = ('Current Week', 'Next Week', 'Monthly')
LEGACY = ('Current Week Expiry', 'Next Week Expiry', 'Monthly Expiry')


def select_choice(values, choice):
    if not values or 'Expiry Choice' not in values[0]:
        raise RuntimeError('Consolidated sheet schema missing Expiry Choice')
    index = values[0].index('Expiry Choice')
    return [values[0][:index]] + [r[:index] for r in values[1:]
        if len(r) > index and r[index] == choice]


def appended_row(response):
    # Never infer a row from a preceding read: other expiry jobs can append.
    address = response.get('updates', {}).get('updatedRange', '')
    match = re.search(r'!A(\d+):', address)
    if not match:
        raise RuntimeError('Append row not confirmed; inspect sheet before rerunning')
    return int(match.group(1))


def read_studies(book, tabs):
    summary = book.worksheet(SUMMARY).get_all_values()
    logs = book.worksheet(LOGS).get_all_values()
    summaries = {t: select_choice(summary, c) for t, c in zip(LEGACY, CHOICES)}
    logsets = {t: select_choice(logs, c) for t, c in zip(LEGACY, CHOICES)}
    rolling = {}
    for tab in tabs:
        if tab not in LEGACY:
            from rolling_sheet_store import physical_title, select_study
            physical, family, choice = physical_title(tab)
            if physical not in rolling:
                rolling[physical] = book.worksheet(physical).get_all_values()
                rolling[family + ' Logs'] = book.worksheet(family + ' Logs').get_all_values()
            summaries[tab] = select_study(rolling[physical], family, choice)
            logsets[tab] = select_study(rolling[family + ' Logs'], family, choice)
    return summaries, logsets


class ScopedWorksheet:
    """Expose original column positions while retaining physical shared-row indexes."""
    def __init__(self, sheet, headers, choice):
        self.sheet, self.headers, self.choice = sheet, headers, choice
        self.owned = set()

    def get_all_values(self):
        values = self.sheet.get_all_values()
        if not values or values[0] != self.headers + ['Expiry Choice']:
            raise RuntimeError('Unexpected consolidated schema; refusing to write')
        n = len(self.headers)
        return [self.headers] + [r[:n] if len(r) > n and r[n] == self.choice else []
            for r in values[1:]]

    def append_rows(self, rows, **kwargs):
        if any(len(r) != len(self.headers) for r in rows):
            raise ValueError('Row width differs from schema')
        result = self.sheet.append_rows([r + [self.choice] for r in rows],
            value_input_option='RAW', insert_data_option='INSERT_ROWS',
            table_range='A1')
        first = appended_row(result)
        self.owned.update(range(first, first + len(rows)))
        return result

    def append_row(self, row, **kwargs):
        return self.append_rows([row])

    def _update(self, update):
        start = update['range'].split(':')[0]
        first = int(re.fullmatch(r'A(\d+)', start).group(1))
        rows = update['values']
        if any(first + i not in self.owned for i in range(len(rows))):
            raise RuntimeError('Refusing to overwrite a row not reserved by this collector')
        if any(len(r) != len(self.headers) for r in rows):
            raise ValueError('Row width differs from schema')
        return {'range': start, 'values': [r + [self.choice] for r in rows]}

    def update(self, range_name, values, **kwargs):
        item = self._update({'range': range_name, 'values': values})
        return self.sheet.update(range_name=item['range'], values=item['values'],
            value_input_option='RAW')

    def batch_update(self, updates, **kwargs):
        return self.sheet.batch_update([self._update(u) for u in updates],
            value_input_option='RAW')


def open_scoped(book, title, headers, choice):
    sheet = ScopedWorksheet(book.worksheet(title), headers, choice)
    sheet.get_all_values()  # Fail closed if the migration/schema is incomplete.
    return sheet


def reserve_daily(sheet, day, headers):
    if any(r and r[0] == day for r in sheet.get_all_values()[1:]):
        raise RuntimeError('Existing date and expiry choice; duplicate run refused')
    row = [''] * len(headers)
    row[0] = day
    row[headers.index('Run Status')] = 'PREPARING ENTRY'
    return appended_row(sheet.append_row(row))
