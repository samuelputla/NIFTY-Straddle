"""One-off read-only FYERS recovery. No orders, Sheet writes, or token output."""
import collections
import json
import math
import os
from pathlib import Path
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import gspread
from google.oauth2.service_account import Credentials

IST = ZoneInfo('Asia/Kolkata')
BOOK = '1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI'
OUT = Path('recovery-evidence')
OUT.mkdir(exist_ok=True)
report = {'checked_at': datetime.now(IST).isoformat(), 'requests': [], 'vix': [], 'stop_minutes': [], 'unavailable': [], 'mode': 'read-only; no Sheet writes or orders'}
session = requests.Session()
token = os.environ['FYERS_ACCESS_TOKEN'].strip()
session.headers['Authorization'] = token if token.startswith('M2DACFCYUO-100:') else 'M2DACFCYUO-100:' + token
expired_blocked = False
auth_blocked = False
expired_requests = 0

def numeric(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None

def candles(symbol, start, end, expired=False):
    global expired_blocked, auth_blocked, expired_requests
    if auth_blocked or (expired and (expired_blocked or expired_requests >= 10)):
        return {}
    if expired:
        expired_requests += 1
    route = '/history/fno/expired/historical-data' if expired else '/history'
    params = dict(symbol=symbol, resolution='1', date_format='1', range_from=start, range_to=end)
    if expired:
        params.update(include_oi='0', include_greeks='0')
    else:
        params['cont_flag'] = '0'
    try:
        response = session.get('https://api-t1.fyers.in/data' + route, params=params, timeout=(4, 25), allow_redirects=False)
        try:
            body = response.json()
        except ValueError:
            body = {}
        status = {'symbol': symbol, 'from': start, 'to': end, 'endpoint': route, 'http': response.status_code, 'code': body.get('code'), 'status': body.get('s'), 'candles': len(body.get('candles', []))}
        report['requests'].append(status)
        if response.status_code == 401 or body.get('code') in (-16, '-16'):
            auth_blocked = True
        if response.status_code in (403, 429) or body.get('code') in (-99, '-99'):
            if expired:
                expired_blocked = True
        if response.status_code != 200 or body.get('s') != 'ok':
            return {}
        if body.get('symbol') and body['symbol'] != symbol:
            return {}
        result = {}
        for row in body.get('candles', []):
            if len(row) < 6 or any(numeric(x) is None for x in row[:6]):
                return {}
            stamp = datetime.fromtimestamp(float(row[0]), IST)
            if stamp.second or stamp.microsecond or stamp.date().isoformat() < start or stamp.date().isoformat() > end:
                continue
            if not 0 < row[3] <= min(row[1], row[4]) <= max(row[1], row[4]) <= row[2] or stamp in result:
                return {}
            result[stamp] = row
        (OUT / (symbol.replace(':', '_') + '_' + start + ('_expired' if expired else '') + '.json')).write_text(json.dumps(body), encoding='utf-8')
        return result
    except requests.RequestException:
        report['requests'].append({'symbol': symbol, 'from': start, 'endpoint': route, 'status': 'network request unavailable'})
        return {}
    finally:
        time.sleep(1.3)

def records(values):
    return [(i, dict(zip(values[0], row))) for i, row in enumerate(values[1:], 2) if row]

try:
    credentials = Credentials.from_service_account_info(json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']), scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
    client = gspread.authorize(credentials)
    client.set_timeout((4, 20))
    book = client.open_by_key(BOOK)
    summaries = records(book.worksheet('Straddle Fixed Summary').get_all_values())
    logs = records(book.worksheet('Straddle Fixed Logs').get_all_values())
    missing_days = sorted({r['Date'] for _, r in logs if r.get('India VIX', '') == ''} | {r['Date'] for _, r in summaries if r.get('Vix at 09:30 AM', '') == ''})
    for day in missing_days:
        history = candles('NSE:INDIAVIX-INDEX', day, day)
        target = datetime.fromisoformat(day + 'T09:30:00+05:30')
        bar = history.get(target)
        if bar:
            report['vix'].append({'date': day, 'value': bar[1], 'bar': bar[:6], 'basis': 'FYERS 09:30 one-minute candle OPEN; historical reconstruction, not original live retrieval'})
        else:
            report['unavailable'].append({'date': day, 'field': 'VIX', 'reason': 'Exact 09:30 minute candle unavailable'})
    groups = collections.defaultdict(list)
    for rowno, row in logs:
        for side in ('CE', 'PE'):
            if row.get(side + ' SL Hit') == 'HIT' and (not row.get(side + ' Hit Time') or not row.get(side + ' Exit Time')):
                groups[row[side + ' Symbol']].append((rowno, row, side))
    contract_cache = {}
    for symbol, items in sorted(groups.items()):
        legacy_symbol = symbol
        expiry = datetime.strptime(items[0][1]['Expiry'], '%d-%m-%Y').date().isoformat()
        if expiry not in contract_cache:
            reply = session.get('https://api-t1.fyers.in/data/history/fno/expired/underlying-symbols', params={'symbol': 'NSE:NIFTY50-INDEX', 'expiry_date': expiry}, timeout=(4,25), allow_redirects=False)
            body = reply.json()
            (OUT / ('contracts_' + expiry + '.json')).write_text(json.dumps(body), encoding='utf-8')
            data = body.get('data', {})
            contracts = data.get('contracts', {}).get('options', []) if body.get('s') == 'ok' else []
            if data.get('expiry_date') != expiry:
                contracts = []
            contract_cache[expiry] = contracts
            report['requests'].append({'endpoint': 'expired contract lookup', 'expiry': expiry, 'http': reply.status_code, 'code': body.get('code'), 'status': body.get('s'), 'contract_count': len(contracts)})
            time.sleep(1.3)
        contracts = contract_cache[expiry]
        strike = str(int(float(items[0][1]['ATM'])))
        option_type = items[0][2]
        matches = [x for x in contracts if isinstance(x,str) and x.startswith('NSE:NIFTY') and x.endswith(strike + option_type)]
        if symbol not in contracts:
            if len(matches) != 1:
                report['unavailable'].append({'symbol':symbol,'reason':'No unique expired contract mapping from official expiry lookup'})
                continue
            symbol = matches[0]
        report.setdefault('symbol_mappings', []).append({'saved_symbol':legacy_symbol,'history_symbol':symbol,'expiry':expiry,'strike':strike,'side':option_type})
        days = sorted({r['Date'] for _, r, _ in items})
        history = candles(symbol, days[0], days[-1])
        endpoint = 'history'
        if not history and not auth_blocked:
            history = candles(symbol, days[0], days[-1], expired=True)
            endpoint = 'expired history'
        for rowno, row, side in items:
            day = row['Date']
            start = datetime.fromisoformat(day + 'T' + row['Entry Time'] + '+05:30')
            minute = start.replace(second=0, microsecond=0)
            end = datetime.fromisoformat(day + 'T15:00:00+05:30')
            threshold = numeric(row.get(side + ' Stop Price'))
            if threshold is None:
                continue
            first = history.get(minute)
            if not first or first[2] >= threshold:
                report['unavailable'].append({'row': rowno, 'side': side, 'reason': 'Entry-minute coverage or ordering ambiguous'})
                continue
            current = minute + timedelta(minutes=1)
            crossed = None
            complete = True
            while current < end:
                bar = history.get(current)
                if not bar:
                    complete = False
                    break
                if bar[2] >= threshold:
                    crossed = current
                    break
                current += timedelta(minutes=1)
            if complete and crossed:
                report['stop_minutes'].append({'row': rowno, 'date': day, 'choice': row['Expiry Choice'], 'sl': row['SL %'], 'side': side, 'symbol': legacy_symbol, 'history_symbol': symbol, 'stop': threshold, 'minute': crossed.strftime('%H:%M:00'), 'candle': history[crossed][:6], 'source': endpoint, 'basis': 'SIMULATED first one-minute high crossing; complete minute coverage from entry; actual tick/fill time unknown'})
            else:
                report['unavailable'].append({'row': rowno, 'side': side, 'reason': 'No continuous minute path to a threshold crossing'})
    report['auth'] = 'rejected' if auth_blocked else 'verified by returned historical candles' if any(r.get('candles', 0) for r in report['requests']) else 'not verified'
    report['expired_requests'] = expired_requests
    report['aggregate_oi'] = 'Unrecoverable from individual contract candle OI: original chain scope and retrieval snapshot unavailable; no substitution made'
except Exception as error:
    report['error_type'] = type(error).__name__
finally:
    (OUT / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('RECOVERY_REPORT=' + json.dumps(report, separators=(',', ':')))

