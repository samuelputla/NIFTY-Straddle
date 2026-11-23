"""Publish dated Multi Strike combinations as values, using deterministic row blocks."""
import os
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from itertools import product
from datetime import date

BOOK = '1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI'
START = '2026-11-11'


def records(rows):
    return [dict(zip(rows[0], row)) for row in rows[1:] if row] if rows else []


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def day(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        return ''


def build(fixed_logs, fixed_summary, strangle_logs, snapshots):
    sn = {r.get('Event ID'): r for r in records(snapshots)}
    summaries = {(r.get('Date'), r.get('Expiry Choice'), r.get('Expiry')): r
                 for r in records(fixed_summary)}
    fixed, strangle = defaultdict(dict), defaultdict(dict)

    def prices_complete(row, fields):
        values = [number(row.get(field)) for field in fields]
        return all(value is not None and value > 0 for value in values)

    def greeks(prefix, symbols):
        legs = [sn.get(prefix + side, {}) for side in ('CE', 'PE')]
        if any(leg.get('Symbol') != symbol for leg, symbol in zip(legs, symbols)):
            return (None, None)
        values = [[number(leg.get(field)) for leg in legs] for field in ('Delta', 'Theta')]
        return tuple(-sum(pair) if all(x is not None for x in pair) else None for pair in values)

    for r in records(fixed_logs):
        d, choice, expiry = r.get('Date'), r.get('Expiry Choice'), r.get('Expiry')
        sl = r.get('SL %')
        if day(d) < START or not choice or not prices_complete(r, ('CE Entry', 'PE Entry', 'CE Exit Price', 'PE Exit Price')):
            continue
        net = number(summaries.get((d, choice, expiry), {}).get(f'{sl}% Profit'))
        if net is None:
            continue
        strike = r['ATM']
        key = (choice, expiry, sl)
        if key in fixed[d]:
            raise ValueError(f'Duplicate completed Fixed Entry scenario: {d} {key}')
        fixed[d][key] = ([d, choice, expiry, sl, strike, strike], net,
                        greeks(f'{d}|Fixed Entry|{choice}|{sl}|1|',
                               [r.get('CE Symbol'), r.get('PE Symbol')]))

    for r in records(strangle_logs):
        d, choice, expiry = r.get('Date'), r.get('Expiry Choice'), r.get('Expiry')
        distance, sl = r.get('Distance %'), r.get('SL %')
        net = number(r.get('Net P&L'))
        if day(d) < START or not choice or net is None or not prices_complete(r, ('CE Entry', 'PE Entry', 'CE Exit', 'PE Exit')):
            continue
        key = (choice, expiry, distance, sl)
        if key in strangle[d]:
            raise ValueError(f'Duplicate completed Short Strangle scenario: {d} {key}')
        strangle[d][key] = ([choice, expiry, distance, sl, r['CE Strike'], r['PE Strike']], net,
                            greeks(f'{d}|Short Strangle|{choice} {distance}%|{sl}|1|',
                                   [r.get('CE Symbol'), r.get('PE Symbol')]))

    grouped = {}
    for d in sorted(fixed.keys() & strangle.keys()):
        if len(fixed[d]) != 27 or len(strangle[d]) != 81:
            print(f'Session {d} is incomplete: {len(fixed[d])} Fixed and {len(strangle[d])} Strangle scenarios')
            continue
        rows = []
        for (f, fn, fg), (s, snet, sg) in product(fixed[d].values(), strangle[d].values()):
            greek = [float(round(a + b, 6)) if a is not None and b is not None else ''
                     for a, b in zip(fg, sg)]
            rows.append([*f[:3], float(f[3]), float(f[4]), float(f[5]), *s[:2],
                         *map(float, s[2:]), float(fn), float(snet), float(fn + snet), *greek])
        grouped[d] = rows
    return grouped


def publish(book):
    from sheet_retries import retry_reserved_io

    source_ranges = ["'Straddle Fixed Logs'!A:AF", "'Straddle Fixed Summary'!A:CF",
                     "'Short Strangle Logs'!A:AB", "'Option Entry Snapshots'!A:S"]
    sources = retry_reserved_io(lambda: book.values_batch_get(source_ranges)['valueRanges'])
    grouped = build(*(r.get('values', []) for r in sources))
    if not grouped:
        raise RuntimeError('No paired completed sessions found; existing logs preserved')
    ws = book.worksheet('Multi Strike Logs')
    original = retry_reserved_io(lambda: ws.get('A2:A', value_render_option='FORMULA'))
    formula = bool(original and original[0] and str(original[0][0]).startswith('='))
    blocks = defaultdict(list)
    if not formula:
        for index, row in enumerate(original, 2):
            if row and day(row[0]):
                blocks[row[0]].append(index)
    first = len(original) + 2 if not formula else 2
    # Validate before writing and reuse existing ranges on every rerun.
    plan = []
    recent = set(sorted(grouped)[-2:])
    for d in sorted(grouped, reverse=True):
        if d in blocks and d not in recent and os.getenv('REPUBLISH_ALL') != 'true':
            continue
        rows, old = grouped[d], blocks.get(d, [])
        size = len(rows)
        if old and (len(old) != size or old != list(range(old[0], old[0] + len(old)))):
            raise RuntimeError(f'Existing block for {d} is partial or changed size; review before writing')
        start = old[0] if old else first
        if not old:
            first += size
        plan.append((start, rows))
    if ws.row_count < first - 1:
        retry_reserved_io(lambda: ws.resize(rows=first + 5000))
    for start, rows in plan:
        # One atomic values update per session. Migration overwrites the formula
        # anchor with the first block. New sessions append to a fixed range.
        retry_reserved_io(lambda: ws.update(range_name=f'A{start}:Q{start + len(rows) - 1}',
                                            values=rows, value_input_option='RAW'))
    print(f'Published {sum(map(len, grouped.values()))} combinations across {len(grouped)} sessions')


def main():
    import gspread
    import json
    from google.oauth2.service_account import Credentials
    credentials = Credentials.from_service_account_info(
        json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),
        scopes=['https://www.googleapis.com/auth/spreadsheets'])
    client = gspread.authorize(credentials)
    client.set_timeout((5, 30))
    publish(client.open_by_key(BOOK))


if __name__ == '__main__':
    main()
