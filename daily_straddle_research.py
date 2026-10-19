"""Independent read-only research recorder. Never imports or writes core strategy.

One additional SymbolUpdate socket (top of book, not full market depth), capped
at 17 symbols. All broker REST work is serial, limited, and outside core entry.
Raw observations are not fills, and this program never computes trading signals.
"""
import copy
import csv
from datetime import datetime, time, timedelta
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import threading
import time as clock
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws

IST = ZoneInfo("Asia/Kolkata")
BOOK = "1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI"
CORE = "Nifty Daily Straddle Logs"
SUMMARY = "Daily Straddle Research"
EVENTS = "Daily Straddle Research Events"
INDEX, VIX = "NSE:NIFTY50-INDEX", "NSE:INDIAVIX-INDEX"
VERSION = "daily-research-v1"
MAX_SYMBOLS, MAX_REQUESTS = 17, 200
HOLIDAY_SOURCE = "https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf"
# Remaining 2026 normal-session closures, checked against NSE's F&O circular.
# This is a session calendar, not an economic-event dataset or a trading filter.
KNOWN_CLOSURES = {"2026-10-20":"Dussehra", "2026-11-10":"Diwali-Balipratipada",
                  "2026-11-24":"Guru Nanak Jayanti", "2026-12-25":"Christmas"}
SUMMARY_HEADERS = ["Date", "Recorder", "Status", "Started At IST", "Updated At IST",
    "Core Entry Time", "CE Symbol", "PE Symbol", "Option Expiry", "Future Symbol",
    "Future Expiry", "Socket Messages Saved", "Dropped Messages", "Reconnects",
    "REST Requests", "REST Status", "Core Rows Observed", "Quality Flags",
    "Raw Data Run URL", "Opening Range High", "Opening Range Low", "Opening Range Minutes",
    "Previous High", "Previous Low", "Previous Close", "Day Open", "Futures OI Status",
    "Greeks Status", "Event Calendar Status", "Fee Schedule Status", "Raw Started At IST",
    "Raw Last Received At IST", "Socket Symbol Count", "Last Core Read At IST"]
EVENT_HEADERS = ["Event ID", "Date", "Observed At IST", "Event Type", "SL %",
    "Core Entry Time", "CE Symbol", "PE Symbol", "Details JSON", "Raw Data Run URL"]
TICK_HEADERS = ["received_at_ist", "received_epoch_ns", "received_monotonic_ns", "symbol",
    "type", "ltp", "bid_price", "ask_price", "bid_size", "ask_size", "last_traded_qty",
    "vol_traded_today", "last_traded_time", "exch_feed_time", "open_price", "high_price",
    "low_price", "prev_close_price", "avg_trade_price", "tot_buy_qty", "tot_sell_qty",
    "source_to_receipt_ms", "source_time_status"]


def now():
    return datetime.now(IST)


def stamp():
    return now().isoformat(timespec="milliseconds")


def number(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def critical_window():
    t = now().time().replace(tzinfo=None)
    return time(9, 29, 30) <= t < time(9, 31) or time(14, 59, 30) <= t < time(15, 0, 30)


def bounded(call, seconds=6):
    """A timed-out broker request permanently disables further broker REST work."""
    done, box = threading.Event(), {}
    def invoke():
        try:
            box["value"] = call()
        except Exception as exc:
            box["error"] = exc
        finally:
            done.set()
    threading.Thread(target=invoke, daemon=True).start()
    if not done.wait(seconds):
        raise TimeoutError("Request deadline exceeded")
    if "error" in box:
        raise box["error"]
    return box["value"]


class Recorder:
    def __init__(self):
        self.date = now().date().isoformat()
        self.run_url = os.getenv("GITHUB_SERVER_URL", "https://github.com") + "/" + os.getenv(
            "GITHUB_REPOSITORY", "samuelputla/NIFTY-Straddle") + "/actions/runs/" + os.getenv("GITHUB_RUN_ID", "local")
        self.folder = Path(os.getenv("RESEARCH_OUTPUT_DIR", "research_capture")) / self.date
        self.folder.mkdir(parents=True, exist_ok=True)
        self.inbox = queue.Queue(maxsize=50000)
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.final_ready = threading.Event()
        self.socket = None
        self.subscribed = set()
        self.desired = {INDEX, VIX}
        self.options = {}
        self.fixed_band = None
        self.core_symbols = set()
        self.future = None
        self.flags = set()
        self.pending_events = []
        self.sheets_finalized = False
        self.stats = dict(zip(SUMMARY_HEADERS, [""] * len(SUMMARY_HEADERS)))
        self.stats.update({"Date": self.date, "Recorder": VERSION, "Status": "STARTING",
            "Started At IST": stamp(), "Socket Messages Saved": 0, "Dropped Messages": 0,
            "Reconnects": 0, "REST Requests": 0, "REST Status": "READY",
            "Core Rows Observed": 0, "Raw Data Run URL": self.run_url,
            "Futures OI Status": "NOT YET RECEIVED", "Greeks Status": "NOT YET RECEIVED",
            "Event Calendar Status": "UNCONFIGURED - NO EVENT EXCLUSION APPLIED",
            "Fee Schedule Status": "UNCONFIGURED - NO EXECUTION NET P&L CLAIM"})
        if now().time().replace(tzinfo=None) > time(9, 15):
            self.flags.add("STARTED AFTER 09:15; inspect opening coverage")
        self.previous_ticks = {}
        self.symbol_quality = {}
        self.minutes = {}
        self.last_core = {}
        self.api_halted = False
        self.last_request = 0.0
        self.symbol_revisions = 0
        self.subscription_halted = False
        self.attempt_id = os.getenv("GITHUB_RUN_ID", "local") + "-" + os.getenv("GITHUB_RUN_ATTEMPT", "1") + "-" + now().strftime("%H%M%S")

    def emit(self, kind, data):
        item = {"kind": kind, "received_at_ist": stamp(), "received_epoch_ns": clock.time_ns(),
                "received_monotonic_ns": clock.monotonic_ns(), "data": data}
        try:
            self.inbox.put_nowait(item)
        except queue.Full:
            with self.lock:
                self.stats["Dropped Messages"] += 1
                self.flags.add("QUEUE OVERFLOW - INCOMPLETE RAW CAPTURE")
            self.stop.set()

    def message(self, message):
        # Never print or retain authentication/control payloads from the SDK.
        if isinstance(message, dict) and message.get("symbol") and message.get("type") in ("sf", "if", "dp"):
            self.emit("tick", message)
        elif isinstance(message, dict) and str(message.get("code")) in ("-429", "429", "-16"):
            self.api_halted = True
            self.emit("collector_event", {"type": "BROKER LIMIT/AUTH STOP", "code": message.get("code")})
            self.stop.set()

    def on_open(self):
        with self.lock:
            self.stats["Reconnects"] += int(bool(self.subscribed))
            symbols = sorted(self.desired)
            if self.stop.is_set():
                return
            try:
                bounded(lambda: self.socket.subscribe(symbols=symbols, data_type="SymbolUpdate"))
            except Exception as exc:
                self.emit("collector_event", {"type": "SUBSCRIPTION FAILED; research stopped", "error_type":type(exc).__name__})
                self.subscription_halted = True
                self.stop.set()
                return
            self.subscribed = set(symbols)
        self.emit("collector_event", {"type": "SOCKET CONNECTED", "symbols": symbols})

    def update_subscription(self):
        # SDK subscription changes can make token-mapping REST requests. Do not
        # make them during core entry/finalization either, or churn all day.
        if critical_window() or self.stop.is_set() or self.subscription_halted:
            return
        desired = {INDEX, VIX} | ({self.future["symbol"]} if self.future else set()) | self.core_symbols
        # Keep core's exact contracts even if the market moves outside the band.
        center = self.stats.get("Core Strike")
        if not number(center) and self.options:
            center = sorted(self.options)[len(self.options) // 2]
        band = set()
        if self.fixed_band is not None:
            band = self.fixed_band
        elif number(center):
            for strike in sorted(self.options, key=lambda k: abs(k - float(center)))[:5]:
                band.update(self.options[strike].values())
            if self.core_symbols:
                self.fixed_band = band.copy()
        desired.update(band)
        if len(desired) > MAX_SYMBOLS:
            self.flags.add("SUBSCRIPTION CAP; surrounding strikes omitted")
            essential = {INDEX, VIX} | self.core_symbols | ({self.future["symbol"]} if self.future else set())
            desired = essential | set(sorted(desired - essential)[:MAX_SYMBOLS-len(essential)])
        with self.lock:
            self.desired = desired
        if self.socket and self.subscribed and desired != self.subscribed:
            removed, added = self.subscribed - desired, desired - self.subscribed
            try:
                if removed:
                    bounded(lambda: self.socket.unsubscribe(symbols=sorted(removed), data_type="SymbolUpdate"))
                if added:
                    bounded(lambda: self.socket.subscribe(symbols=sorted(added), data_type="SymbolUpdate"))
            except Exception as exc:
                self.subscription_halted = True
                self.emit("collector_event", {"type":"SUBSCRIPTION FAILED; research stopped", "error_type":type(exc).__name__})
                self.stop.set()
                return
            self.subscribed = desired.copy()
            self.symbol_revisions += 1
            self.emit("collector_event", {"type": "SUBSCRIPTION CHANGE", "symbols": sorted(desired)})
        self.stats["Socket Symbol Count"] = len(desired)

    def request(self, method, payload):
        if method not in {"optionchain", "futures_chain", "history"}:
            raise ValueError("Read-only broker method allowlist")
        if self.api_halted or self.stop.is_set() or critical_window():
            return None
        if self.stats["REST Requests"] >= MAX_REQUESTS:
            self.api_halted = True
            self.emit("collector_event", {"type": "LOCAL REST BUDGET EXHAUSTED"})
            return None
        # At most one request per 30 seconds; no retries or parallel SDK calls.
        if clock.monotonic() - self.last_request < 30:
            return None
        self.last_request = clock.monotonic()
        with self.lock:
            self.stats["REST Requests"] += 1
        app = os.getenv("FYERS_CLIENT_ID", "M2DACFCYUO-100")
        token = os.environ["FYERS_ACCESS_TOKEN"].strip()
        try:
            def invoke():
                client = fyersModel.FyersModel(client_id=app, token=token, log_path="")
                return getattr(client, method)(data=payload)
            result = bounded(invoke)
            if not isinstance(result, dict) or result.get("s") != "ok":
                code = result.get("code") if isinstance(result, dict) else "INVALID RESPONSE"
                # Any broker error disables optional REST for the session; no retry storm.
                self.api_halted = True
                self.emit("collector_event", {"type": "REST DISABLED", "method": method, "code": code})
                if str(code) in ("-429", "429", "-16"):
                    self.stop.set()  # Release this socket as well on limit/auth errors.
                return None
            self.emit("rest", {"method": method, "request": payload, "response": result})
            return result
        except Exception as exc:
            self.api_halted = True
            self.emit("collector_event", {"type": "REST DISABLED", "method": method,
                                          "error_type": type(exc).__name__})
            return None

    def rest_worker(self):
        schedule = {"optionchain": 0, "futures_chain": 0, "previous": 0, "index_1m": 0, "future_oi": 0}
        pre_entry_done, post_entry_done = False, False
        while not self.stop.wait(.5):
            t = now().time().replace(tzinfo=None)
            if self.api_halted or critical_window() or t < time(9, 15):
                continue
            mono = clock.monotonic()
            if mono - self.last_request >= 30 and (
                    not pre_entry_done and time(9, 29) <= t < time(9, 29, 30) or
                    not post_entry_done and time(9, 31) <= t < time(9, 32)):
                self.request("optionchain", {"symbol":INDEX, "strikecount":2, "timestamp":"", "greeks":"1"})
                if t < time(9, 30):
                    pre_entry_done = True
                else:
                    post_entry_done = True
                continue
            job = next((key for key, due in schedule.items() if due <= mono and
                (key != "future_oi" or self.future) and
                (key != "index_1m" or t >= time(9, 31)) and
                (key != "future_oi" or t >= time(9, 31))), None)
            if not job or mono - self.last_request < 30:
                continue
            schedule[job] = mono + (300 if job in ("optionchain", "future_oi") else 600)
            if job in ("futures_chain", "previous"):
                schedule[job] = float("inf")
            if job in ("optionchain", "futures_chain"):
                payload = {"symbol": INDEX}
                if job == "optionchain":
                    payload.update(strikecount=2, timestamp="", greeks="1")
                self.request(job, payload)
            else:
                end = now().replace(second=0, microsecond=0) - timedelta(seconds=1)
                start = datetime.combine(now().date(), time(9, 15), IST)
                symbol = self.future["symbol"] if job == "future_oi" else INDEX
                payload = {"symbol": symbol, "date_format": "0", "resolution": "1",
                    "range_from": str(int(start.timestamp())), "range_to": str(int(end.timestamp())), "cont_flag": "0"}
                if job == "previous":
                    payload.update(resolution="D", date_format="1", range_from=(now().date()-timedelta(days=14)).isoformat(),
                                   range_to=(now().date()-timedelta(days=1)).isoformat())
                if job == "future_oi":
                    # Exact expiry contract, never a continuous/rolled OI series.
                    payload["oi_flag"] = "1"
                self.request("history", payload)

    def sheet_worker(self):
        summary = events = core = None
        seen = set()
        try:
            credentials = Credentials.from_service_account_info(json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
                scopes=["https://www.googleapis.com/auth/spreadsheets"])
            gc = gspread.authorize(credentials)
            gc.set_timeout((3, 5))
            book = gc.open_by_key(BOOK)
            # Research writes are confined to these two exact worksheet IDs/headers.
            def ensure(title, headers):
                try:
                    sheet = book.worksheet(title)
                except gspread.WorksheetNotFound:
                    sheet = book.add_worksheet(title, rows=20000 if title == EVENTS else 2000, cols=len(headers))
                actual = sheet.row_values(1)
                if not actual:
                    sheet.update(range_name="A1", values=[headers], value_input_option="RAW")
                    sheet.freeze(rows=1)
                elif actual != headers:
                    raise ValueError("Research worksheet schema mismatch")
                return sheet
            summary = ensure(SUMMARY, SUMMARY_HEADERS)
            events = ensure(EVENTS, EVENT_HEADERS)
            core = book.worksheet(CORE)
            previous = summary.get("A2:D2000")
            matching = [i+2 for i, row in enumerate(previous) if row and row[0] == self.date]
            if matching and len(previous[matching[-1]-2]) > 3 and previous[matching[-1]-2][3]:
                # A fresh runner lacks earlier raw ticks. Never call a rerun complete.
                self.flags.add("RESTART/RERUN; separate raw segment, inspect combined coverage")
            row_number = matching[-1] if matching else len(previous)+2
            seen = {row[0] for row in events.get("A2:A20000") if row}
            while True:
                try:
                    if self.stop.is_set():
                        self.final_ready.wait(20)
                        if not self.final_ready.is_set():
                            break
                    values = [] if self.stop.is_set() else core.get("A1:AC1000")  # read only
                    if values:
                        headers = values[0]
                        required = {"Date", "SL %", "CE Symbol", "PE Symbol", "Run Type"}
                        if not required.issubset(headers):
                            raise ValueError("Core log schema mismatch; refused guessed columns")
                        rows = [dict(zip(headers, row)) for row in values[1:] if row]
                        rows = [r for r in rows if r.get("Date") == self.date and r.get("Run Type") == "SCHEDULED PAPER"]
                        if not self.stop.is_set():
                            self.emit("core", rows)
                    with self.lock:
                        state = copy.deepcopy(self.stats)
                        pending = copy.deepcopy(self.pending_events)
                        state["Quality Flags"] = "; ".join(sorted(self.flags)) or "NO ISSUES FLAGGED; coverage not yet certified"
                    state["Updated At IST"] = stamp()
                    row = [state.get(h, "") for h in SUMMARY_HEADERS]
                    summary.update(range_name=f"A{row_number}", values=[row], value_input_option="RAW")
                    unsaved = [r for r in pending if r[0] not in seen]
                    if unsaved:
                        events.append_rows(unsaved, value_input_option="RAW")
                        seen.update(r[0] for r in unsaved)
                    if self.stop.is_set():
                        self.sheets_finalized = True
                        break
                except Exception as exc:
                    self.emit("collector_event", {"type": "SHEETS FAILURE; raw capture continues", "error_type": type(exc).__name__})
                    # Low-rate bounded recovery; never rapid retries.
                    if self.stop.is_set():
                        break
                self.stop.wait(60)
        except Exception as exc:
            self.emit("collector_event", {"type": "SHEETS DISABLED; raw capture continues", "error_type": type(exc).__name__})

    def process(self, item, ticks, raw):
        with self.lock:
            self._process(item, ticks, raw)

    def socket_error(self, message):
        code = message.get("code") if isinstance(message, dict) else None
        self.emit("collector_event", {"type":"SOCKET ERROR; inspect coverage", "code":code})
        if str(code) in ("-429", "429", "-16"):
            self.api_halted = True
            self.stop.set()

    def _process(self, item, ticks, raw):
        kind, data = item["kind"], item["data"]
        if kind == "tick":
            received = datetime.fromisoformat(item["received_at_ist"])
            symbol = data["symbol"]
            row = {k: data.get(k, "") for k in TICK_HEADERS}
            row.update({k: item[k] for k in ("received_at_ist", "received_epoch_ns", "received_monotonic_ns")})
            source = data.get("exch_feed_time")
            row["source_time_status"] = "MISSING EXCHANGE FEED TIME"
            if number(source) and float(source) > 0:
                lag = received.timestamp() - float(source)
                row["source_to_receipt_ms"] = round(lag*1000, 1)
                row["source_time_status"] = "VALID" if -2 <= lag <= 10 else "STALE OR CLOCK SKEW"
            ticks.writerow(row)
            q = self.symbol_quality.setdefault(symbol, {"messages":0, "first_received_at_ist":item["received_at_ist"],
                "last_received_at_ist":"", "missing_exchange_time":0, "stale_or_clock_skew":0,
                "missing_or_invalid_top_of_book":0, "max_inter_update_seconds":0})
            q["messages"] += 1
            q["last_received_at_ist"] = item["received_at_ist"]
            q["missing_exchange_time"] += int(row["source_time_status"] == "MISSING EXCHANGE FEED TIME")
            q["stale_or_clock_skew"] += int(row["source_time_status"] == "STALE OR CLOCK SKEW")
            valid_book = all(number(data.get(k)) and float(data[k]) > 0 for k in ("bid_price", "ask_price", "bid_size", "ask_size"))
            valid_book = valid_book and float(data["ask_price"]) >= float(data["bid_price"])
            q["missing_or_invalid_top_of_book"] += int(not valid_book)
            mono = item["received_monotonic_ns"]
            last = self.previous_ticks.get(symbol)
            if last:
                q["max_inter_update_seconds"] = max(q["max_inter_update_seconds"], (mono-last)/1e9)
            if last and mono-last > 15_000_000_000 and symbol in self.core_symbols:
                self.flags.add("SELECTED OPTION INTER-UPDATE GAP >15S; may be quiet market or feed gap")
            self.previous_ticks[symbol] = mono
            self.stats["Socket Messages Saved"] += 1
            self.stats["Raw Started At IST"] = self.stats["Raw Started At IST"] or item["received_at_ist"]
            self.stats["Raw Last Received At IST"] = item["received_at_ist"]
            # Build an explicitly receipt-time sampled path. Authoritative candles
            # are independently downloaded and retain their own candle timestamps.
            if number(data.get("ltp")) and row["source_time_status"] == "VALID":
                key = (symbol, received.replace(second=0, microsecond=0).isoformat())
                p = float(data["ltp"])
                if key not in self.minutes:
                    self.minutes[key] = [p, p, p, p, 1]
                else:
                    bar = self.minutes[key]
                    bar[1], bar[2], bar[3], bar[4] = max(bar[1], p), min(bar[2], p), p, bar[4]+1
            return
        raw.write(json.dumps(item, separators=(",", ":"), default=str) + "\n")
        if kind == "collector_event":
            event_type = data.get("type", "")
            if event_type not in ("SOCKET CONNECTED", "SUBSCRIPTION CHANGE") and not (event_type.startswith("SOCKET CLOSED") and self.stop.is_set()):
                self.flags.add(event_type)
            identity = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:24]
            self.pending_events.append([identity, self.date, item["received_at_ist"], event_type, "", "", "", "",
                                        json.dumps(data, separators=(",", ":")), self.run_url])
            if "REST DISABLED" in event_type or "BUDGET" in event_type or "BROKER" in event_type:
                self.stats["REST Status"] = event_type
            return
        if kind == "core":
            self.stats["Last Core Read At IST"] = item["received_at_ist"]
            self.stats["Core Rows Observed"] = len(data)
            pairs = {(r.get("CE Symbol"), r.get("PE Symbol"), r.get("Entry Time"), r.get("Expiry")) for r in data}
            if len(pairs) > 1:
                self.flags.add("MULTIPLE CORE ENTRIES; refusing to guess selected contracts")
                return
            if data:
                r = data[0]
                selected = {r.get("CE Symbol", ""), r.get("PE Symbol", "")}
                if all(s.startswith("NSE:") for s in selected) and len(selected) == 2:
                    self.core_symbols = selected
                    self.stats.update({"CE Symbol": r["CE Symbol"], "PE Symbol": r["PE Symbol"],
                        "Core Entry Time": r.get("Entry Time", ""), "Option Expiry": r.get("Expiry", ""),
                        "Core Strike": r.get("ATM", "")})
                    self.update_subscription()
            for r in data:
                key = str(r.get("SL %"))
                # Full raw checkpoint kept; compact event log only when meaningful
                # state changes, not just Last Update heartbeat timestamps.
                state = {k:v for k,v in r.items() if k not in {"Last Update", "Total P&L", "CE P&L", "PE P&L"}}
                if state == self.last_core.get(key):
                    continue
                self.last_core[key] = state
                identity = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:24]
                event = [identity, self.date, item["received_at_ist"], "CORE STATE OBSERVED (DELAYED SHEET READ)",
                    r.get("SL %", ""), r.get("Entry Time", ""), r.get("CE Symbol", ""), r.get("PE Symbol", ""),
                    json.dumps(r, separators=(",", ":")), self.run_url]
                with self.lock:
                    self.pending_events.append(event)
            return
        if kind != "rest":
            return
        method, payload, response = data["method"], data["request"], data["response"]
        if method == "optionchain":
            entries = response.get("data", {}).get("optionsChain", [])
            self.options = {}
            for r in entries:
                if r.get("option_type") in ("CE", "PE") and number(r.get("strike_price")) and r.get("symbol"):
                    self.options.setdefault(int(float(r["strike_price"])), {})[r["option_type"]] = r["symbol"]
            options = [r for r in entries if r.get("option_type") in ("CE", "PE")]
            complete = options and all(all(number(r.get("greeks", {}).get(k)) for k in ("delta", "gamma", "theta", "vega", "iv")) for r in options)
            self.stats["Greeks Status"] = "PRESENT IN LATEST CHAIN; see retrieval time" if complete else "MISSING/PARTIAL IN LATEST CHAIN"
            if self.core_symbols and not self.core_symbols.issubset({r.get("symbol") for r in options}):
                self.flags.add("CORE OPTIONS OUTSIDE LATEST OI/GREEKS CHAIN RANGE")
            self.update_subscription()
        elif method == "futures_chain":
            eligible = [r for r in response.get("data", []) if r.get("symbol", "").endswith("FUT") and
                number(r.get("expiry")) and datetime.fromtimestamp(float(r["expiry"]), IST).date() >= now().date()]
            if eligible:
                self.future = min(eligible, key=lambda r: float(r["expiry"]))
                self.stats["Future Symbol"] = self.future["symbol"]
                self.stats["Future Expiry"] = datetime.fromtimestamp(float(self.future["expiry"]), IST).isoformat()
                self.update_subscription()
            else:
                self.flags.add("FUTURES CONTRACT UNAVAILABLE")
        elif method == "history":
            candles = response.get("candles", [])
            if payload.get("oi_flag") == "1":
                complete = bool(candles) and all(len(c) == 7 and number(c[6]) and float(c[6]) >= 0 for c in candles)
                self.stats["Futures OI Status"] = "VERIFIED SEVENTH FIELD; exact contract" if complete else "MISSING/INVALID OI; DO NOT INFER"
            elif payload["resolution"] == "D":
                prior = [c for c in candles if len(c) >= 6 and datetime.fromtimestamp(c[0], IST).date() < now().date()]
                if prior:
                    row = max(prior, key=lambda c:c[0])
                    self.stats.update({"Previous High": row[2], "Previous Low": row[3], "Previous Close": row[4]})
            elif payload["symbol"] == INDEX:
                bars = {int(c[0]): c for c in candles if len(c) >= 6 and datetime.fromtimestamp(c[0], IST).date() == now().date()}
                opening = [c for c in bars.values() if time(9,15) <= datetime.fromtimestamp(c[0], IST).time().replace(tzinfo=None) < time(9,30)]
                self.stats["Opening Range Minutes"] = len(opening)
                if len(opening) == 15:
                    self.stats.update({"Opening Range High": max(c[2] for c in opening),
                        "Opening Range Low": min(c[3] for c in opening), "Day Open": min(opening,key=lambda c:c[0])[1]})

    def run(self):
        if self.date in KNOWN_CLOSURES:
            (self.folder / f"manifest-{self.attempt_id}.json").write_text(json.dumps({
                "date":self.date, "status":"SKIPPED - KNOWN NSE F&O HOLIDAY", "holiday":KNOWN_CLOSURES[self.date],
                "source":HOLIDAY_SOURCE, "broker_requests":0, "core_files_changed":False}, indent=2), encoding="utf-8")
            print(f"Research recorder: NSE F&O holiday {self.date}; no broker connection")
            return
        if now().year != 2026:
            self.flags.add("SESSION CALENDAR NEEDS CURRENT-YEAR REVIEW")
        if now().weekday() > 4:
            print("Research recorder: weekend; no capture")
            return
        if now().time().replace(tzinfo=None) >= time(15, 3):
            print("Research recorder: session ended; no backdated capture")
            return
        if not os.getenv("FYERS_ACCESS_TOKEN", "").strip():
            raise ValueError("FYERS_ACCESS_TOKEN missing")
        app = os.getenv("FYERS_CLIENT_ID", "M2DACFCYUO-100")
        token = os.environ["FYERS_ACCESS_TOKEN"].strip()
        self.socket = data_ws.FyersDataSocket(access_token=f"{app}:{token}", litemode=False,
            log_path=str(self.folder), write_to_file=False, reconnect=True, reconnect_retry=3,
            on_connect=self.on_open, on_message=self.message,
            on_error=self.socket_error,
            on_close=lambda _: self.emit("collector_event", {"type": "SOCKET CLOSED; inspect coverage"}))
        worker = threading.Thread(target=self.rest_worker, daemon=True)
        sheets = threading.Thread(target=self.sheet_worker, daemon=True)
        tick_path = self.folder / f"ticks-{self.attempt_id}.csv.gz"
        raw_path = self.folder / f"context-events-{self.attempt_id}.jsonl.gz"
        with gzip.open(tick_path, "wt", newline="", encoding="utf-8") as tickfile, gzip.open(raw_path, "wt", encoding="utf-8") as raw:
            writer = csv.DictWriter(tickfile, fieldnames=TICK_HEADERS)
            writer.writeheader()
            self.stats["Status"] = "COLLECTING - RESEARCH ONLY"
            worker.start()
            sheets.start()
            threading.Thread(target=self.socket.connect, daemon=True).start()
            flush_at = clock.monotonic()
            try:
                while not self.stop.is_set() and now().time().replace(tzinfo=None) < time(15, 3):
                    try:
                        item = self.inbox.get(timeout=.25)
                    except queue.Empty:
                        continue
                    self.process(item, writer, raw)
                    self.update_subscription()  # apply any deferred core-symbol change after 09:31
                    if clock.monotonic() - flush_at >= 10:
                        tickfile.flush()
                        raw.flush()
                        flush_at = clock.monotonic()
                        if sum(p.stat().st_size for p in self.folder.iterdir() if p.is_file()) > 512*1024*1024:
                            self.flags.add("512 MIB LOCAL STORAGE CAP; RESEARCH STOPPED")
                            self.stop.set()
            finally:
                self.stats["Status"] = "FINISHED - REVIEW COVERAGE" if not self.stop.is_set() else "STOPPED - INCOMPLETE CAPTURE"
                if not self.core_symbols:
                    self.flags.add("NO CONFIRMED CORE ENTRY; NOT A TRADE REPLAY")
                for symbol in self.core_symbols:
                    quality = self.symbol_quality.get(symbol)
                    if not quality:
                        self.flags.add("CORE OPTION HAS NO RECORDED MESSAGES")
                        continue
                    if quality["missing_exchange_time"] or quality["stale_or_clock_skew"]:
                        self.flags.add("CORE OPTION TIMESTAMP QUALITY; inspect per-symbol manifest counters")
                    if quality["missing_or_invalid_top_of_book"]:
                        self.flags.add("CORE OPTION TOP-OF-BOOK GAPS; execution study needs exclusions")
                    try:
                        entry = datetime.fromisoformat(self.date+"T"+self.stats["Core Entry Time"]).replace(tzinfo=IST)
                        if datetime.fromisoformat(quality["first_received_at_ist"]) > entry:
                            self.flags.add("CORE ENTRY PRECEDES FIRST OPTION MESSAGE; entry fill study incomplete")
                    except ValueError:
                        self.flags.add("CORE ENTRY TIME NOT PARSEABLE")
                if self.stats["Socket Messages Saved"] == 0:
                    self.flags.add("NO MARKET MESSAGES; check holiday/auth/feed")
                self.stop.set()
                try:
                    bounded(self.socket.close_connection, 3)
                except Exception:
                    self.flags.add("SOCKET CLOSE DEADLINE")
                worker.join(7)
                while not self.inbox.empty():
                    self.process(self.inbox.get_nowait(), writer, raw)
                self.final_ready.set()
                sheets.join(25)
                while not self.inbox.empty():
                    self.process(self.inbox.get_nowait(), writer, raw)
        with (self.folder / f"sampled-1m-{self.attempt_id}.csv").open("w", newline="", encoding="utf-8") as handle:
            output = csv.writer(handle)
            output.writerow(["symbol", "receipt_minute_ist", "open", "high", "low", "close", "observations", "basis"])
            for (symbol, minute), bar in sorted(self.minutes.items()):
                output.writerow([symbol, minute, *bar, "RECEIPT-TIME SAMPLE; NOT EXCHANGE OHLC"])
        manifest = {"version": VERSION, "date": self.date, "status": self.stats, "flags": sorted(self.flags),
            "per_symbol_quality":self.symbol_quality,
            "sheet_final_acknowledged": self.sheets_finalized, "max_symbols": MAX_SYMBOLS,
            "core_files_changed": False, "orders_supported": False, "subscription_revisions": self.symbol_revisions,
            "files": [{"name":p.name,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p in self.folder.iterdir() if p.is_file() and p.suffix in (".gz", ".csv")]}
        (self.folder / f"manifest-{self.attempt_id}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Research capture saved: {self.folder}; messages={self.stats['Socket Messages Saved']}; flags={len(self.flags)}", flush=True)
        if self.stats["Dropped Messages"] or not self.sheets_finalized:
            raise RuntimeError("Research capture needs review; raw artifact retained")


if __name__ == "__main__":
    Recorder().run()

