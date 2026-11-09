"""Four physical rolling tabs; expiry choice remains part of every row identity."""
from rolling_engine import CHOICES, SUMMARY_HEADERS, LOG_HEADERS
from sheets_resilience import RollingSheetStore

FAMILIES = ('Time Based', 'Delta Based')
SCHEMAS = {f'{family} {kind}': headers for family in FAMILIES
           for kind, headers in (('Summary', SUMMARY_HEADERS), ('Logs', LOG_HEADERS))}


def physical_title(title):
    for family in FAMILIES:
        for choice in CHOICES:
            if title == f'{family} - {choice}':
                return f'{family} Summary', family, choice
            if title == f'{family} - {choice} Logs':
                return f'{family} Logs', family, choice
    raise ValueError('Unknown rolling study: ' + title)


def row_key(title, row):
    headers = SCHEMAS[title]
    family = title.rsplit(' ', 1)[0]
    choice = row[headers.index('Expiry Choice')]
    if row[headers.index('Family')] != family or choice not in CHOICES:
        raise RuntimeError('Rolling row family or expiry choice mismatch')
    if title.endswith(' Logs'):
        expected = f'{row[1]}|{family}|{choice}|{row[4]}|{row[5]}'
        if row[0] != expected:
            raise RuntimeError('Rolling Event ID mismatch')
        return row[0]
    return row[0], family, choice


class ConsolidatedRollingStore:
    def __init__(self, book):
        # Read all columns, and fail closed when migration is missing/incomplete.
        self.cache = RollingSheetStore(book, SCHEMAS, row_key=row_key)

    def check_day(self, day):
        self.cache.check_day(day)

    def checkpoint(self, summaries, logsets):
        grouped = {title: [] for title in SCHEMAS}
        for title, rows in [(n, [r]) for n, r in summaries] + logsets:
            physical, family, choice = physical_title(title)
            for row in rows:
                headers = SCHEMAS[physical]
                if row[headers.index('Family')] != family or row[headers.index('Expiry Choice')] != choice:
                    raise RuntimeError('Generated row does not match study')
                grouped[physical].append(row)
        # Multiple expiries share each summary: process as row sets, not single rows.
        self.cache.checkpoint([], list(grouped.items()))


def select_study(values, family, choice):
    headers = SUMMARY_HEADERS if values and values[0] == SUMMARY_HEADERS else LOG_HEADERS
    if not values or values[0] != headers:
        raise RuntimeError('Unexpected consolidated rolling schema')
    fi, ci = headers.index('Family'), headers.index('Expiry Choice')
    return [headers] + [r for r in values[1:] if len(r) > max(fi, ci)
                       and r[fi] == family and r[ci] == choice]
