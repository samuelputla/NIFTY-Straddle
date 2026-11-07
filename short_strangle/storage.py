"""One batched write per minute, deterministic day ranges, no append retries."""
from short_strangle.engine import SUMMARY, LOGS, HEADERS, SUMMARY_HEADERS, summary_rows, DISTANCES, CHOICES, LEVELS

def quoted(name): return "'" + name.replace("'", "''") + "'"

def col(n):
    result = ''
    while n:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result

class Store:
    def __init__(self, book, day):
        self.book = book
        self.day = day
        self.schemas = {SUMMARY: SUMMARY_HEADERS, LOGS: HEADERS}
        tabs = {w.title: w for w in book.worksheets()}
        if any(n not in tabs for n in self.schemas):
            raise RuntimeError('Run setup to create Short Strangle tabs first')
        self.tabs = tabs
        values = book.values_batch_get([quoted(n) + '!A1:' + col(len(h)) for n, h in self.schemas.items()])['valueRanges']
        if len(values) != len(self.schemas): raise RuntimeError('Incomplete startup Sheet read')
        self.start = {}
        for (name, headers), value in zip(self.schemas.items(), values):
            rows = value.get('values', [])
            if not rows or rows[0] != headers: raise RuntimeError('Schema mismatch: ' + name)
            date_index = 1 if name == LOGS else 0
            if any(len(r) > date_index and r[date_index] == day for r in rows[1:]):
                raise RuntimeError('Existing same-day session; restart refused to prevent re-entry')
            self.start[name] = len(rows) + 1

    def save(self, scenarios):
        incoming = {SUMMARY: summary_rows(scenarios), LOGS: [s.row() for s in scenarios]}
        self._write(incoming)

    def reserve(self):
        """Claim the session before market capture; slow Sheets must not delay entry."""
        summaries, logs = [], []
        for distance in DISTANCES:
            for choice in CHOICES:
                summaries.append([self.day, distance, choice, '', 'STARTING'] + [''] * 10)
                for pct in LEVELS:
                    row = [''] * len(HEADERS)
                    row[:6] = [f'strangle-v1|{self.day}|{distance}|{choice}|{pct}', self.day, distance, choice, '', pct]
                    row[25] = 'STARTING'
                    logs.append(row)
        self._write({SUMMARY:summaries, LOGS:logs})

    def _write(self, incoming):
        data = []
        for name, rows in incoming.items():
            end = self.start[name] + len(rows) - 1
            if end > self.tabs[name].row_count:
                self.tabs[name].resize(rows=end + 1000)
            data.append({'range': quoted(name) + '!A' + str(self.start[name]), 'values': rows})
        self.book.values_batch_update({'valueInputOption': 'RAW', 'data': data})
