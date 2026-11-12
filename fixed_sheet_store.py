"""Shared fixed-entry tabs: expiry isolation and server-allocated append ranges."""
import json
import os
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
        allocations = os.getenv('FIXED_ROW_ALLOCATIONS')
        self.allocation = json.loads(allocations)[sheet.title][choice] if allocations else None

    def get_all_values(self):
        values = self.sheet.get_all_values()
        if not values or values[0] != self.headers + ['Expiry Choice']:
            raise RuntimeError('Unexpected consolidated schema; refusing to write')
        n = len(self.headers)
        return [self.headers] + [r[:n] if len(r) > n and r[n] == self.choice else []
            for r in values[1:]]

    def append_rows(self, rows, **kwargs):
        if not rows or any(len(r) != len(self.headers) for r in rows):
            raise ValueError('Invalid append rows for worksheet schema')
        values = [[value if value is not None else '' for value in row] + [self.choice]
                  for row in rows]

        if self.allocation is not None:
            first, count = self.allocation
            if self.owned or len(rows) != count:
                raise RuntimeError('Write does not match the collector row allocation')
            from gspread.utils import rowcol_to_a1
            last = rowcol_to_a1(first + count - 1, len(self.headers) + 1)
            address = f'A{first}:{last}'
            if any(value != '' for row in self.sheet.get(address) for value in row):
                raise RuntimeError('Allocated rows already contain data')
            self.sheet.update(range_name=address, values=values, value_input_option='RAW')
            self.owned.update(range(first, first + count))
            return {'updates': {'updatedRange': f"'{self.sheet.title}'!{address}"}}

        def cell(value):
            if isinstance(value, bool):
                return {'userEnteredValue': {'boolValue': value}}
            if isinstance(value, (int, float)):
                return {'userEnteredValue': {'numberValue': value}}
            return {'userEnteredValue': {'stringValue': str(value)}}

        # Append after the sheet's last populated row without inserting at a
        # table-relative location. Other collectors must never shift these rows.
        self.sheet.spreadsheet.batch_update({'requests': [{'appendCells': {
            'sheetId': self.sheet.id,
            'rows': [{'values': [cell(value) for value in row]} for row in values],
            'fields': 'userEnteredValue',
        }}]})
        actual = self.sheet.get_all_values(value_render_option='UNFORMATTED_VALUE')
        width = len(self.headers) + 1
        key_columns = [self.headers.index(name)
                       for name in ('Date', 'Entry Time', 'SL %', 'Run Type')
                       if name in self.headers] + [width - 1]
        keys = [tuple(row[j] for j in key_columns) for row in values]
        actual_keys = [tuple(row[j] for j in key_columns) if len(row) >= width else None
                       for row in actual]
        matches = [i + 1 for i, key in enumerate(actual_keys)
                   if key == keys[0] and actual_keys[i:i + len(keys)] == keys]
        if len(matches) != 1:
            raise RuntimeError('Could not uniquely locate appended rows; refusing to update')
        first = matches[0]
        self.owned.update(range(first, first + len(rows)))
        last_col = ''
        while width:
            width, remainder = divmod(width - 1, 26)
            last_col = chr(65 + remainder) + last_col
        return {'updates': {'updatedRange': f"'{self.sheet.title}'!A{first}:{last_col}{first + len(rows) - 1}"}}

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


def allocate_session_rows(book, day, test_mode=False):
    """Plan disjoint ranges once, before any parallel collector starts."""
    allocations = {}
    for title, count in ((SUMMARY, 1), (LOGS, 9)):
        sheet = book.worksheet(title)
        values = sheet.get_all_values()
        if not values or values[0][0] != 'Date' or values[0][-1] != 'Expiry Choice':
            raise RuntimeError(f'Unexpected worksheet layout: {title}')
        if not test_mode and any(row and row[0] == day for row in values[1:]):
            raise RuntimeError(f'{title} already contains {day} rows; duplicate run refused')
        first = len(values) + 1
        allocations[title] = {choice: [first + i * count, count]
                              for i, choice in enumerate(CHOICES)}
        required = first + len(CHOICES) * count - 1
        if required > sheet.row_count:
            sheet.resize(rows=required)
    return allocations


if __name__ == '__main__':
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import gspread
    from market_calendar import session_allowed

    day = datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
    test_mode = os.getenv('TEST_MODE') == 'true'
    allowed, reason = session_allowed(day)
    if not test_mode and not allowed:
        print(reason)
    else:
        client = gspread.service_account_from_dict(
            json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),
            scopes=['https://www.googleapis.com/auth/spreadsheets'],
        )
        client.set_timeout((3, 8))
        book = client.open_by_key('1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI')
        allocations = allocate_session_rows(book, day, test_mode)
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            print('rows=' + json.dumps(allocations, separators=(',', ':')), file=output)
