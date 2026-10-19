"""Live FYERS market-data observer for Straddle V2. PAPER ONLY; no order APIs.

Dedicated worksheets and state; never reads/writes core position state. Quotes
are observations, not guaranteed executions. Replay requires full ordered prices.
"""
import copy
from datetime import datetime, time, timedelta
import json
import os
import queue
import threading
import time as clock
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from request_timing import run_with_timeout
from straddle_v2_engine import Engine, HEADERS, LOG_HEADERS, VERSION, atm, valid

IST = ZoneInfo("Asia/Kolkata")
BOOK = "1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI"
STRATEGY = "Straddle V2 Strategy"
LOGS = "Straddle V2 Logs"
INDEX = "NSE:NIFTY50-INDEX"
APP = os.getenv("FYERS_CLIENT_ID", "M2DACFCYUO-100")
TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
messages = queue.Queue(maxsize=100000)
work = queue.Queue(maxsize=200)
cache = {}
socket = None
subscribed = set()
lock = threading.Lock()


def now():
    return datetime.now(IST)


def iso():
    return now().isoformat(timespec="milliseconds")


def api(method, payload):
    def call():
        client = fyersModel.FyersModel(client_id=APP, token=TOKEN, log_path="")
        result = getattr(client, method)(payload)
        if result.get("s") != "ok":
            raise RuntimeError(f"FYERS {method}: {result.get('code')}")
        return result
    return run_with_timeout(call, 6)


def worksheet(book, title, headers, rows):
    try:
        tab = book.worksheet(title)
    except gspread.WorksheetNotFound:
        tab = book.add_worksheet(title, rows, len(headers))
    actual = tab.row_values(1)
    if not actual:
        tab.update(values=[headers], range_name="A1", value_input_option="RAW")
        tab.freeze(rows=1)
    elif actual != headers:
        raise RuntimeError(f"{title}: schema mismatch; refused to overwrite")
    return tab


def writer(strategy, logs, row_number, seen):
    while True:
        item = work.get()
        try:
            if item is None:
                return
            row, events = item
            for attempt in range(3):
                try:
                    pending = [event for event in events if event[0] not in seen]
                    if pending:
                        logs.append_rows(pending, value_input_option="RAW")
                        seen.update(e[0] for e in pending)
                    strategy.update(values=[row], range_name=f"A{row_number}", value_input_option="RAW")
                    break
                except Exception as exc:
                    print(f"V2 sheet checkpoint error: {type(exc).__name__}", flush=True)
                    if attempt == 2:
                        # Do not discard state/events on a transient final write failure.
                        work.put(item, timeout=2)
                    clock.sleep(2)
        finally:
            work.task_done()


def on_message(message):
    symbol, price = message.get("symbol"), message.get("ltp")
    if not symbol or not valid(price):
        return
    received = now()
    raw = message.get("last_traded_time", message.get("tt"))
    source = None
    if raw:
        try:
            source = datetime.fromtimestamp(float(raw), IST)
        except (ValueError, TypeError, OverflowError):
            return
        if not -2 <= (received-source).total_seconds() <= 10:
            return  # No stale historical LTPs used as fresh observations.
    with lock:
        cache[symbol] = (float(price), received, source is not None)
    try:
        messages.put_nowait((symbol, float(price), received))
    except queue.Full:
        print("V2 observation queue full; stopping to avoid silent data loss", flush=True)
        os._exit(2)


def subscribe(symbols):
    global subscribed
    additions = set(symbols)-subscribed
    if additions and socket:
        socket.subscribe(symbols=sorted(additions), data_type="SymbolUpdate")
        subscribed.update(additions)


def snapshot(symbols, max_age=10, max_skew=2):
    with lock:
        values = {s:cache.get(s) for s in symbols}
    if any(v is None for v in values.values()):
        return None
    times = [v[1] for v in values.values()]
    if (now()-min(times)).total_seconds() > max_age or (max(times)-min(times)).total_seconds() > max_skew:
        return None
    return {s:v[0] for s,v in values.items()}


def chain_selection():
    result = api("optionchain", {"symbol":INDEX,"strikecount":12,"timestamp":""})["data"]
    expiry = min(datetime.strptime(x["date"], "%d-%m-%Y").date()
                 for x in result["expiryData"] if datetime.strptime(x["date"], "%d-%m-%Y").date() >= now().date())
    # Blank timestamp selects the nearest expiry. Match all exact returned symbols;
    # no expiry weekday or synthetic option symbol construction is used.
    options = {}
    for item in result["optionsChain"]:
        if item.get("option_type") in ("CE", "PE") and valid(item.get("strike_price")):
            options.setdefault(int(item["strike_price"]), {})[item["option_type"]] = item["symbol"]
    if not options:
        raise RuntimeError("Nearest-expiry option chain empty")
    return expiry, options, result


def metadata(engine):
    """Run off the entry path; supporting data cannot postpone entry."""
    fields = {}
    try:
        data = api("optionchain", {"symbol":INDEX,"strikecount":12,"timestamp":""})["data"]
        fields.update({"VIX":data.get("indiavixData",{}).get("ltp", ""),
                       "CE OI":data.get("callOi", ""), "PE OI":data.get("putOi", ""),
                       "Metadata Retrieved At":iso()})
    except Exception:
        pass
    try:
        today = now().date()
        candles = api("history", {"symbol":INDEX,"resolution":"D","date_format":"1",
            "range_from":(today-timedelta(days=14)).isoformat(),"range_to":today.isoformat(),"cont_flag":"1"})["candles"]
        prior = sorted((r for r in candles if datetime.fromtimestamp(r[0],IST).date()<today), key=lambda r:r[0])
        if prior:
            fields.update({"Prev High":prior[-1][2], "Prev Low":prior[-1][3], "Prev Close":prior[-1][4]})
            regime_spot = engine.state.get("regime_spot")
            if valid(regime_spot):
                fields["PDR Regime"] = "INSIDE_PDR" if prior[-1][3] <= regime_spot <= prior[-1][2] else "OUTSIDE_PDR"
        current = [r for r in candles if datetime.fromtimestamp(r[0],IST).date()==today]
        if current:
            fields["Day Open"] = current[-1][1]
    except Exception:
        pass
    messages.put(("__metadata__", fields, now()))


def main():
    global socket
    credentials = Credentials.from_service_account_info(json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(credentials)
    gc.set_timeout((3,8))
    book = gc.open_by_key(BOOK)
    strategy = worksheet(book, STRATEGY, HEADERS, 1000)
    logs = worksheet(book, LOGS, LOG_HEADERS, 10000)
    if os.getenv("SETUP_ONLY", "false").lower() == "true":
        print("V2 strategy/log worksheets ready; FYERS not contacted")
        return
    if not TOKEN:
        raise RuntimeError("FYERS_ACCESS_TOKEN missing")
    today = now().date().isoformat()
    rows = strategy.get_all_values()
    matches = [(i+1,r) for i,r in enumerate(rows) if i and r and r[0]==today]
    if len(matches)>1:
        raise RuntimeError("Duplicate V2 date; refused second position")
    engine = None
    if matches:
        row_number, old = matches[0]
        state_text = old[HEADERS.index("State JSON")] if len(old)>HEADERS.index("State JSON") else ""
        if state_text:
            engine = Engine(json.loads(state_text))
            if engine.state["status"] != "OPEN":
                print("V2 already finalized today; no re-entry")
                return
            engine.state["quality"] = "RESTART GAP / REVIEW REQUIRED"
    else:
        row_number = len(rows)+1
        strategy.append_row([today,VERSION,"REFINED PAPER","WAITING ENTRY"], value_input_option="RAW")
    finish = datetime.combine(now().date(),time(14,55),IST)
    if now() >= finish and engine is None:
        blank = dict(zip(HEADERS, matches[0][1])) if matches else {"Date":today,"Strategy":VERSION,"Run Type":"REFINED PAPER"}
        blank.update(Status="MISSED ENTRY", **{"Data Quality":"Started after 14:55; no fabricated entry", "Last Update":iso()})
        strategy.update(values=[[blank.get(h,"") for h in HEADERS]],range_name=f"A{row_number}",value_input_option="RAW")
        return
    seen = {r[0] for r in logs.get_all_values()[1:] if r}
    threading.Thread(target=writer,args=(strategy,logs,row_number,seen),daemon=True).start()
    expiry, options, _ = chain_selection()
    symbols = [INDEX] + [s for pair in options.values() for s in pair.values()]
    if engine:
        symbols += [leg["symbol"] for leg in engine.state["legs"].values()]
    def on_open():
        socket.subscribe(symbols=symbols, data_type="SymbolUpdate")
        subscribed.update(symbols)
    socket = data_ws.FyersDataSocket(access_token=f"{APP}:{TOKEN}",log_path="",litemode=False,
        write_to_file=False,reconnect=True,on_connect=on_open,on_message=on_message,
        on_error=lambda _:print("V2 feed error; awaiting reconnect",flush=True))
    threading.Thread(target=socket.connect,daemon=True).start()
    target = datetime.combine(now().date(),time(9,32) if expiry==now().date() else time(9,30),IST)
    heartbeat, last_pair, last_quote_log = 0.0, clock.monotonic(), 0.0
    metadata_started = False
    regime_spot = None
    last_refresh = clock.monotonic()
    while now() < finish:
        try:
            symbol, price, received = messages.get(timeout=.2)
        except queue.Empty:
            symbol, price, received = "", None, now()
        if symbol == "__metadata__" and engine:
            engine.state["metadata"].update(price)
        if regime_spot is None and time(9,30) <= now().time().replace(tzinfo=None) < time(9,30,10):
            with lock:
                candidate = cache.get(INDEX)
            if candidate and (now()-candidate[1]).total_seconds() <= 2:
                regime_spot = candidate[0]
        if engine is None and now() >= target:
            with lock:
                index = cache.get(INDEX)
            if index and (now()-index[1]).total_seconds()<=10:
                k0 = atm(index[0])
                provisional = options.get(k0,{})
                initial = snapshot(list(provisional.values())+[INDEX]) if len(provisional)==2 else None
                if initial:
                    synthetic = k0+initial[provisional["CE"]]-initial[provisional["PE"]]
                    strike = atm(synthetic)
                    selected = options.get(strike,{})
                    pair = snapshot(list(selected.values())+[INDEX]) if len(selected)==2 else None
                    if pair:
                        engine = Engine.enter(today,expiry.isoformat(),iso(),pair[INDEX],k0,synthetic,strike,selected,
                            {side:pair[selected[side]] for side in ("CE","PE")})
                        engine.state["regime_spot"] = regime_spot
                        print(f"V2 captured {strike} at {engine.state['entry_time']}",flush=True)
                        subscribe(list(selected.values()))
            # Only refresh a missing strike universe before entry, outside peak
            # capture when candidates are already present; actual time is retained.
            if engine is None and clock.monotonic()-last_refresh > 60:
                try:
                    expiry, options, _ = chain_selection()
                    subscribe([s for pair in options.values() for s in pair.values()])
                    target = datetime.combine(now().date(),time(9,32) if expiry==now().date() else time(9,30),IST)
                except Exception:
                    pass
                last_refresh=clock.monotonic()
        if engine:
            if not metadata_started:
                threading.Thread(target=metadata,args=(copy.deepcopy(engine),),daemon=True).start()
                metadata_started=True
            legs = engine.state["legs"]
            pair = snapshot([legs[x]["symbol"] for x in ("CE","PE")])
            if pair:
                last_pair = clock.monotonic()
            elif clock.monotonic()-last_pair > 15 and engine.state["status"]=="OPEN":
                engine.state["quality"] = "FEED GAP / REVIEW REQUIRED"
            if symbol in [legs[x]["symbol"] for x in legs] and received >= datetime.fromisoformat(engine.state["entry_time"]):
                side = next(x for x in legs if legs[x]["symbol"]==symbol)
                # Decisions use already-processed event-time prices, never the
                # socket cache which can contain later queued ticks.
                other = "PE" if side=="CE" else "CE"
                prior_time = datetime.fromisoformat(legs[other]["last_time"])
                paired = 0 <= (received-prior_time).total_seconds() <= 2
                engine.observe({side:price},received.isoformat(timespec="milliseconds"),paired=paired)
                if pair and clock.monotonic()-last_quote_log >= 5:
                    engine.event(iso(),"PRICE OBSERVATION",details="Fresh pair sampled every 5s; event transitions logged individually")
                    last_quote_log=clock.monotonic()
            if clock.monotonic()-heartbeat>=10 or engine.events and engine.events[-1][4] not in ("PRICE OBSERVATION",):
                events, engine.events = engine.events, []
                work.put((engine.row(),events),timeout=1)
                heartbeat=clock.monotonic()
            if engine.state["status"] in ("COMPLETED","REVIEW REQUIRED"):
                break
    if engine:
        # Deadline never waits for a new API call. Stale exits remain review-only.
        fresh = snapshot([x["symbol"] for x in engine.state["legs"].values()],max_age=5) is not None
        engine.finish(iso(),fresh=fresh)
        events, engine.events = engine.events, []
        work.put((engine.row(),events),timeout=1)
    else:
        blank={"Date":today,"Strategy":VERSION,"Run Type":"REFINED PAPER","Status":"MISSED ENTRY",
               "Data Quality":"No fresh synchronized pair before deadline","Last Update":iso()}
        work.put(([blank.get(h,"") for h in HEADERS],[]),timeout=1)
    deadline=clock.monotonic()+25
    while work.unfinished_tasks and clock.monotonic()<deadline:
        clock.sleep(.2)
    if work.unfinished_tasks:
        raise RuntimeError("V2 final checkpoint not acknowledged; inspect logs before trusting result")
    print("V2 paper session finalized",flush=True)


if __name__ == "__main__":
    main()

