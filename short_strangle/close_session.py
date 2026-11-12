"""After-close paper reconciliation; never place orders or replace existing exits."""
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from short_strangle.engine import HEADERS, SUMMARY_HEADERS, LEVELS, DISTANCES, CHOICES
from request_timing import run_with_timeout
from short_strangle.candle_check import apply_check

IST = ZoneInfo('Asia/Kolkata')
BOOK = '1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI'
OUT = Path('short_strangle_close_output')

def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None

def positive(value):
    n = number(value)
    return n is not None and n > 0

def candle_mark(response, day):
    """15:00 minute OPEN is a labelled recovery proxy, never a tick fill."""
    if response.get('s') != 'ok':
        return None
    target = int(datetime.fromisoformat(day + 'T15:00:00+05:30').timestamp())
    candles = [c for c in response.get('candles', []) if len(c) >= 6 and c[0] == target]
    if len(candles) != 1 or not positive(candles[0][1]):
        return None
    return float(candles[0][1])

def reconcile(row, marks, day):
    row = list(row) + [''] * (len(HEADERS) - len(row))
    if row[1] != day:
        raise ValueError('Wrong session')
    if not all(positive(row[i]) for i in (13, 14)) or not row[10]:
        return row
    for symbol_col, exit_col, at_col, reason_col in ((11,17,19,21),(12,18,20,22)):
        # A filled stop or observed 15:00 exit is immutable. Ambiguous partial exits
        # are left unresolved rather than silently rewritten.
        if any(row[i] != '' for i in (exit_col, at_col, reason_col)):
            continue
        mark = marks.get(row[symbol_col])
        if positive(mark):
            row[exit_col] = mark
            row[at_col] = day + 'T15:00:00+05:30'
            row[reason_col] = '15:00 EXIT FYERS 1-minute open recovery proxy'
            note = 'Recovered missing exit from FYERS 15:00 minute open; simulated price, stop path unverified'
            row[26] = '; '.join(filter(None, [row[26], note])) if note not in row[26] else row[26]
    complete = all(positive(row[i]) for i in (13,14,17,18,27))
    complete = complete and number(row[24]) is not None and number(row[24]) >= 0
    complete = complete and all(row[i] for i in (19,20,21,22))
    if complete:
        for at in (row[19], row[20]):
            if not at.startswith(day + 'T') or at < row[10]:
                raise ValueError('Invalid exit chronology')
        row[23] = round(sum(round(float(row[e])-float(row[x]),2)*float(row[27])
                            for e,x in ((13,17),(14,18))) - float(row[24]),2)
        row[25] = 'COMPLETED'
    else:
        row[23] = ''
        row[25] = 'INCOMPLETE'
    return row

def main():
    import gspread
    from google.oauth2.service_account import Credentials
    from fyers_apiv3 import fyersModel
    from sheets_resilience import ResilientHTTPClient
    if not os.environ.get('GITHUB_RUN_ID'):
        raise RuntimeError('Use the concurrency-protected workflow')
    now = datetime.now(IST)
    day = os.environ.get('SESSION_DATE') or now.date().isoformat()
    if os.environ.get('GITHUB_EVENT_NAME') == 'push':
        day = json.loads(Path('.automation/short-strangle-close.json').read_text())['requested_session']
    datetime.strptime(day, '%Y-%m-%d')
    if day > now.date().isoformat() or (day == now.date().isoformat() and now.strftime('%H:%M') < '15:01'):
        raise RuntimeError('Reconciliation requires the 15:00 minute to have ended')
    OUT.mkdir(exist_ok=True)
    client = gspread.authorize(Credentials.from_service_account_info(
        json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),
        scopes=['https://www.googleapis.com/auth/spreadsheets']), http_client=ResilientHTTPClient)
    client.set_timeout((3, 12))
    book = client.open_by_key(BOOK)
    data = book.values_batch_get(["'Short Strangle Logs'!A1:AB10000", "'Short Strangle Summary'!A1:O2000"],
                                params={'valueRenderOption':'UNFORMATTED_VALUE'})['valueRanges']
    logs, summary = [d.get('values', []) for d in data]
    if not logs or logs[0] != HEADERS or not summary or summary[0] != SUMMARY_HEADERS:
        raise RuntimeError('Unexpected Sheet schema')
    targets = [(i+1,r) for i,r in enumerate(logs) if len(r)>1 and r[1] == day]
    summaries = [(i+1,r) for i,r in enumerate(summary) if r and r[0] == day]
    if not targets and not summaries:
        print('No existing session; no entries created')
        return
    expected = {(float(d),c,int(p)) for d in DISTANCES for c in CHOICES for p in LEVELS}
    keys = [(float(r[2]),r[3],int(r[5])) for _,r in targets]
    if len(keys) != 81 or set(keys) != expected or len({r[0] for _,r in targets}) != 81:
        raise RuntimeError('Missing/duplicate existing scenarios; no writes')
    if len(summaries) != 9 or {(float(r[1]),r[2]) for _,r in summaries} != {(float(d),c) for d in DISTANCES for c in CHOICES}:
        raise RuntimeError('Missing/duplicate summary groups; no writes')
    (OUT/'before.json').write_text(json.dumps({'logs':targets,'summary':summaries},indent=2),encoding='utf-8')
    # Full-session history for every entered CE/PE, including previously stopped legs.
    symbols = sorted({r[sc] for _,r in targets for sc in (11,12)
                      if len(r)>14 and positive(r[13]) and positive(r[14])})
    api = fyersModel.FyersModel(client_id='M2DACFCYUO-100', token=os.environ['FYERS_ACCESS_TOKEN'].strip(), log_path='')
    evidence, marks, responses = {}, {}, {}
    for symbol in symbols:
        try:
            payload = {'symbol':symbol,'resolution':'1','date_format':'1',
                       'range_from':day,'range_to':day,'cont_flag':'0'}
            saved = Path('option_observations/strangle') / ('history-' + symbol.replace(':','_') + '.json')
            response = json.loads(saved.read_text(encoding='utf-8')) if saved.is_file() else {}
            if candle_mark(response, day) is None:
                refreshed = run_with_timeout(lambda: api.history(payload), 15)
                if refreshed.get('s') == 'ok' or response.get('s') != 'ok':
                    response = refreshed
            mark = candle_mark(response, day)
            evidence[symbol] = {'response':response,'recovery_mark':mark}
            responses[symbol] = response
            if mark is not None: marks[symbol] = mark
        except Exception as error:
            evidence[symbol] = {'error_type':type(error).__name__}
        time.sleep(.4)
    (OUT/'fyers_1500_reference.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    repaired, checks = [], {}
    for i,r in targets:
        checked, details = apply_check(r,responses,day)
        repaired.append((i,reconcile(checked,marks,day)))
        checks[r[0]] = details
    (OUT/'candle_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    updates = []
    for (i,before),(_,after) in zip(targets,repaired):
        if before != after:
            updates.append({'range':f"'Short Strangle Logs'!R{i}:AA{i}", 'values':[after[17:27]]})
    for i,row in summaries:
        group = [r for _,r in repaired if float(r[2]) == float(row[1]) and r[3] == row[2]]
        status = 'COMPLETED' if all(r[25]=='COMPLETED' for r in group) else 'MISSED ENTRY' if all(r[25]=='MISSED ENTRY' for r in group) else 'INCOMPLETE'
        values = [status] + [next(r[23] for r in group if int(r[5]) == p) for p in LEVELS]
        values += ['; '.join(sorted({r[26] for r in group if r[26]}))]
        if row[4:15] != values:
            updates.append({'range':f"'Short Strangle Summary'!E{i}:O{i}", 'values':[values]})
    # Shared concurrency prevents writes from racing the live collector.
    if updates: book.values_batch_update({'valueInputOption':'RAW','data':updates})
    report = {'date':day,'scenarios':len(repaired),'completed':sum(r[25]=='COMPLETED' for _,r in repaired),
              'fyers_symbols_requested':len(symbols),'fyers_1500_marks_available':len(marks),
              'changed_ranges':len(updates),'coverage_notes_retained':True}
    (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

if __name__ == '__main__': main()
