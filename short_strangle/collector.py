"""Dedicated socket collector. Read-only FYERS calls; paper bookkeeping only."""
import csv
import io
import json
import os
import threading
import time
import urllib.request
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_calendar import session_allowed
from option_observations import Observer
from quote_quality import quote_prices
from request_timing import run_with_timeout
from short_strangle.engine import make_scenarios, positive, select_expiries

BOOK = '1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI'
INDEX = 'NSE:NIFTY50-INDEX'
IST = ZoneInfo('Asia/Kolkata')
OUT = Path('short_strangle_output')

def now(): return datetime.now(IST)

def main():
    from fyers_apiv3 import fyersModel
    from fyers_apiv3.FyersWebsocket import data_ws
    import gspread
    from google.oauth2.service_account import Credentials
    from sheets_resilience import ResilientHTTPClient
    from short_strangle.storage import Store

    if not os.environ.get('GITHUB_RUN_ID'):
        raise RuntimeError('Use the dedicated concurrency-protected workflow')
    day = now().date().isoformat()
    allowed, reason = session_allowed(day)
    if not allowed: print(reason); return
    if now().strftime('%H:%M:%S') > '09:30:20':
        raise RuntimeError('Late startup; no paper entries')
    OUT.mkdir(exist_ok=True)
    client = gspread.authorize(Credentials.from_service_account_info(
        json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']),
        scopes=['https://www.googleapis.com/auth/spreadsheets']), http_client=ResilientHTTPClient)
    client.set_timeout((3, 8))
    store = Store(client.open_by_key(BOOK), day)
    store.reserve()
    token = os.environ['FYERS_ACCESS_TOKEN'].strip()
    def call(method, payload):
        # Method names below are exclusively data methods; no order client is exposed.
        if method not in ('optionchain', 'quotes', 'depth', 'history'): raise ValueError('Read-only methods only')
        model = fyersModel.FyersModel(client_id='M2DACFCYUO-100', token=token, log_path='')
        response = run_with_timeout(lambda: getattr(model, method)(payload), 6)
        if response.get('s') != 'ok': raise RuntimeError('Market data unavailable')
        return response
    observations=Observer(store.book,call,day,'strangle')
    req = urllib.request.Request('https://public.fyers.in/sym_details/NSE_FO.csv', headers={'User-Agent':'NiftyPaperResearch'})
    with urllib.request.urlopen(req, timeout=15) as response:
        text = response.read().decode('utf-8-sig')
    contracts, monthly = {}, set()
    for f in csv.reader(io.StringIO(text)):
        if len(f) < 17 or f[13] != 'NIFTY': continue
        expiry = datetime.fromtimestamp(int(f[8]), IST).date().isoformat()
        if expiry < day: continue
        if f[16] in ('CE', 'PE'):
            contracts.setdefault(expiry, {})[(int(float(f[15])), f[16])] = f[9]
        elif f[9].endswith('FUT'): monthly.add(expiry)
    meta = call('optionchain', dict(symbol=INDEX, strikecount=1, timestamp=''))['data']
    listed = [datetime.fromtimestamp(int(x['expiry']), IST).date().isoformat() for x in meta['expiryData']]
    expiry_map = select_expiries(contracts, monthly, listed)
    lock = threading.RLock()
    prices, scenarios = {}, []
    connected = threading.Event()
    journal = (OUT / 'quotes.jsonl').open('a', encoding='utf-8')
    def on_message(message):
        if not isinstance(message, dict): return
        symbol, price = message.get('symbol'), message.get('ltp')
        if not symbol or not positive(price): return
        with lock:
            at = now().isoformat()
            prices[symbol] = (price, time.monotonic())
            observations.tick(symbol,price,at)
            if not journal.closed:
                journal.write(json.dumps({'at':at, 'symbol':symbol, 'price':price}) + '\n')
            for scenario in scenarios: scenario.tick(symbol, price, at)
    socket = data_ws.FyersDataSocket(access_token='M2DACFCYUO-100:' + token,
        log_path='', litemode=True, write_to_file=False, reconnect=True,
        on_connect=lambda: connected.set(), on_close=lambda m: connected.clear(),
        on_error=lambda m: print('Socket warning; inspect coverage'), on_message=on_message)
    threading.Thread(target=socket.connect, daemon=True).start()
    if not connected.wait(15): raise RuntimeError('Socket not connected')
    while now().strftime('%H:%M:%S') < '09:30:00': time.sleep(.2)
    spot = quote_prices(call('quotes', {'symbols': INDEX}), [INDEX])[INDEX]
    spot_at = now().isoformat()
    if spot_at[11:19] > '09:30:20': raise RuntimeError('Missed spot capture window')
    scenarios = make_scenarios(day, spot, spot_at, expiry_map, contracts)
    symbols = sorted({sym for s in scenarios for sym in s.symbols.values()})
    socket.subscribe(symbols=symbols, data_type='SymbolUpdate')
    pending = None
    errors = []
    def persist(snapshot):
        try:
            store.save(snapshot)
            observations.publish()
        except Exception as error: errors.append(type(error).__name__)
    def snapshot():
        import copy
        with lock: saved = copy.deepcopy(scenarios)
        temp = OUT / 'state.tmp'
        temp.write_text(json.dumps({'asof':now().isoformat(), 'scenarios':[asdict(s) for s in saved], 'sheet_errors':errors}, indent=2), encoding='utf-8')
        temp.replace(OUT / 'state.json')
        return saved
    next_save, last_loop, disconnected = 0, time.monotonic(), None
    try:
        while now().strftime('%H:%M:%S') < '15:00:00':
            at, mono = now().isoformat(), time.monotonic()
            with lock:
                fresh = {s:p for s,(p,t) in prices.items() if 0 <= mono-t <= 10}
                for scenario in scenarios:
                    scenario.enter(fresh, at)
                    for side,premium in scenario.entries.items():
                        observations.register('Short Strangle',scenario.choice+' '+str(scenario.distance)+'%',scenario.expiry,scenario.pct,1,side,scenario.symbols[side],scenario.entry_at,premium,round(premium*(1+scenario.pct/100),2))
                    for side,exit_value in scenario.exits.items():
                        observations.exited('Short Strangle',scenario.choice+' '+str(scenario.distance)+'%',scenario.pct,1,side,exit_value[1],exit_value[2])
                    # Evaluate the capture snapshot too; a first leg may move while waiting for its pair.
                    for symbol, price in fresh.items(): scenario.tick(symbol, price, at)
                    if scenario.entries and mono-last_loop > 10: scenario.issue('Collector gap >10 seconds')
                    if scenario.entries and any(sym not in fresh for side,sym in scenario.symbols.items() if side not in scenario.exits):
                        scenario.issue('Open-contract quote gap >10 seconds; stop path incomplete')
                if not connected.is_set():
                    if disconnected is None: disconnected = mono
                    if mono-disconnected > 10:
                        for scenario in scenarios: scenario.issue('Socket disconnected >10 seconds')
                else: disconnected = None
            last_loop = mono
            if mono >= next_save:
                saved = snapshot()
                if pending is None or not pending.is_alive():
                    pending = threading.Thread(target=persist, args=(saved,), daemon=True)
                    pending.start()
                journal.flush()
                next_save = mono + 60
            time.sleep(.2)
        # Require a new post-deadline quote response for final marks, never cached pre-15:00 ticks.
        final_quotes = {}
        try: final_quotes = quote_prices(call('quotes', {'symbols':','.join(symbols)}), symbols)
        except Exception:
            with lock:
                for scenario in scenarios: scenario.issue('Final quote request failed')
        with lock:
            at = now().isoformat()
            for scenario in scenarios: scenario.finish(final_quotes, at)
        saved = snapshot()
        if pending: pending.join(timeout=180)
        if pending and pending.is_alive(): raise RuntimeError('Sheet writer still busy; final state saved for recovery')
        store.save(saved)
        try:
            for scenario in scenarios:
                for side,value in scenario.exits.items():
                    observations.exited('Short Strangle',scenario.choice+' '+str(scenario.distance)+'%',scenario.pct,1,side,value[1],value[2])
            observations.finish()
        except Exception as error:print('Optional option observations unavailable:',type(error).__name__)
        print('Paper session saved: 81 scenarios; no broker orders')
    finally:
        snapshot()
        if hasattr(socket, 'close_connection'): socket.close_connection()
        with lock: journal.close()

if __name__ == '__main__': main()
