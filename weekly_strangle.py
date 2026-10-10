"""Paper-only carry-forward NIFTY weekly strangle monitor.

This module deliberately uses only FYERS market-data APIs and Google Sheets.
There are no order-placement imports or calls.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sys
import threading
import time as time_module
import uuid

import gspread
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from google.oauth2.service_account import Credentials


CLIENT_ID = "M2DACFCYUO-100"
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
GOOGLE_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
SPREADSHEET_ID = "1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI"
SHEET_NAME = "Nifty Weekly Strangle"
LOG_SHEET_NAME = "Nifty Weekly Strangle Logs"
UNDERLYING = "NSE:NIFTY50-INDEX"
IST = ZoneInfo("Asia/Kolkata")
START_TIME = time(9, 30)
MARKET_OPEN = time(9, 15)
ADJUST_TIME = time(15, 25)
END_TIME = time.fromisoformat(os.getenv("WEEKLY_SESSION_END", "15:30"))
TARGET_PREMIUM = 25.0
REPLACEMENT_RATIO = 0.85
INITIAL_DIVERGENCE = 0.50
EOD_DIVERGENCE = 0.80
STRADDLE_STOP = 0.10
PROFIT_TARGET = 0.80
CONTRACT_QTY = int(os.getenv("WEEKLY_CONTRACT_QTY", "65"))
SNAPSHOT_MINUTES = 30
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADERS = [
    "Cycle ID", "Snapshot Time (IST)", "Cycle Start Date", "Expiry", "Status", "Phase",
    "NIFTY Spot", "CE Symbol", "CE Entry Premium", "CE LTP", "CE High Premium", "CE Low Premium",
    "PE Symbol", "PE Entry Premium", "PE LTP", "PE High Premium", "PE Low Premium",
    "Initial Combined Credit", "Realized P&L (Premium Points)", "Open P&L (Premium Points)",
    "Net P&L (Premium Points)", "Net P&L (₹)", "Quantity (Units)", "80% Target (₹)",
    "Premium Divergence %", "Adjustment Count", "Last Event", "Last Event Time (IST)", "Exit Reason", "State JSON",
]
LOG_HEADERS = [
    "Event ID", "Cycle ID", "Event Time (IST)", "Event Type", "Position Action", "Leg",
    "Symbol", "Expiry", "Phase", "Simulated Fill Premium", "Quantity (Units)", "Reason",
    "Realized P&L (₹)", "Cycle Net P&L (₹)", "Cycle Status",
]


def now_ist() -> datetime:
    return datetime.now(IST)


def fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%d-%m-%Y").date()


if not GOOGLE_JSON:
    raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is not set")
if CONTRACT_QTY <= 0:
    raise RuntimeError("WEEKLY_CONTRACT_QTY must be a positive unit count")

credentials = Credentials.from_service_account_info(json.loads(GOOGLE_JSON), scopes=GOOGLE_SCOPES)
sheet = gspread.authorize(credentials).open_by_key(SPREADSHEET_ID)


def column_letter(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def prepare_sheet(tab_name: str, headers: list[str]):
    try:
        ws = sheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
    ws.resize(rows=max(ws.row_count, 1000), cols=max(ws.col_count, len(headers)))
    current = ws.get(f"A1:{column_letter(len(headers))}1")
    current = current[0] if current else []
    if not current:
        ws.update(range_name=f"A1:{column_letter(len(headers))}1", values=[headers], value_input_option="RAW")
    elif current != headers:
        rows = ws.get_all_values()
        has_records = any(any(str(c).strip() for c in r) for r in rows[1:])
        if not has_records and len(current) == len(headers):
            ws.update(range_name=f"A1:{column_letter(len(headers))}1", values=[headers], value_input_option="RAW")
        else:
            raise RuntimeError(f"{tab_name} has an unexpected schema; refusing to rewrite existing rows")
    return ws


sheet_tab = prepare_sheet(SHEET_NAME, HEADERS)
log_tab = prepare_sheet(LOG_SHEET_NAME, LOG_HEADERS)
if os.getenv("WEEKLY_SETUP_ONLY", "false").lower() == "true":
    print(f"Google Sheet tabs ready: {SHEET_NAME}, {LOG_SHEET_NAME}")
    raise SystemExit(0)

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS_ACCESS_TOKEN secret is not set")

fyers = fyersModel.FyersModel(client_id=CLIENT_ID, token=ACCESS_TOKEN, is_async=False, log_path="")
state_lock = threading.RLock()
latest: dict[str, float] = {}
socket_holder: dict[str, object] = {"socket": None}
subscribed: set[str] = set()
stop_event = threading.Event()
last_adjustment_at: datetime | None = None
last_write_at: datetime | None = None
cycle: dict | None = None
current_spot = ""
entry_attempted_date: date | None = None


def option_chain(timestamp: str = "") -> dict:
    response = fyers.optionchain({"symbol": UNDERLYING, "strikecount": 50, "timestamp": timestamp})
    if response.get("s") != "ok":
        raise RuntimeError(f"FYERS option-chain request failed: {response.get('code')} {response.get('message', '')}")
    return response["data"]


def quote(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    response = fyers.quotes({"symbols": ",".join(dict.fromkeys(symbols))})
    if response.get("s") != "ok":
        raise RuntimeError(f"FYERS quote request failed: {response.get('code')} {response.get('message', '')}")
    found = {}
    for item in response.get("d", []):
        value = item.get("v", {})
        symbol = item.get("n") or value.get("symbol")
        try:
            ltp = float(value.get("lp"))
        except (TypeError, ValueError):
            continue
        if symbol and ltp > 0:
            found[symbol] = ltp
    missing = [s for s in symbols if s not in found]
    if missing:
        raise RuntimeError(f"FYERS returned no usable LTP for {missing}")
    return found


def expiry_options(data: dict, expiry_epoch: str | None = None, *, after_date: date | None = None) -> tuple[str, list[dict]]:
    expiries = data.get("expiryData", [])
    today = now_ist().date()
    viable = []
    flags_available = any(entry.get("expiry_flag") for entry in expiries)
    for entry in expiries:
        try:
            exp_date = parse_date(entry["date"])
            epoch = str(entry["expiry"])
        except (KeyError, ValueError, TypeError):
            continue
        expiry_flag = str(entry.get("expiry_flag", "")).upper()
        if flags_available and expiry_flag != "W":
            continue
        if not flags_available and exp_date.weekday() != 1:
            # Fail safely when the API omits contract type information.
            continue
        date_floor = after_date if after_date is not None else today - timedelta(days=1)
        if exp_date > date_floor and (expiry_epoch is None or int(epoch) > int(expiry_epoch)):
            viable.append((exp_date, epoch))
    if not viable:
        raise RuntimeError("No eligible NIFTY weekly expiry was returned by FYERS")
    viable.sort()
    return viable[0][1], data.get("optionsChain", [])


def target_contracts(expiry_epoch: str, premiums: dict[str, float]) -> dict[str, dict]:
    """Choose CE and PE independently by nearest available option-chain LTP."""
    data = option_chain(expiry_epoch)
    chain = data.get("optionsChain", [])
    chosen = {}
    for side in ("CE", "PE"):
        candidates = []
        for item in chain:
            if item.get("option_type") != side:
                continue
            symbol = item.get("symbol")
            try:
                ltp = float(item.get("ltp", item.get("lp")))
                strike = float(item.get("strike_price"))
            except (TypeError, ValueError):
                continue
            if symbol and ltp > 0:
                candidates.append({"symbol": symbol, "ltp": ltp, "strike": strike, "side": side})
        if not candidates:
            raise RuntimeError(f"No {side} contracts in the selected expiry chain")
        chosen[side] = min(candidates, key=lambda c: abs(c["ltp"] - premiums[side]))
    refreshed = quote([chosen["CE"]["symbol"], chosen["PE"]["symbol"]])
    for side in ("CE", "PE"):
        chosen[side]["ltp"] = refreshed[chosen[side]["symbol"]]
        if chosen[side]["ltp"] <= 0:
            raise RuntimeError(f"Selected {side} quote is invalid")
    return chosen


def make_cycle(expiry_epoch: str, ce: dict, pe: dict, reason: str) -> dict:
    stamp = now_ist()
    initial = round(ce["ltp"] + pe["ltp"], 2)
    return {
        "cycle_id": f"{stamp:%Y%m%d}-{uuid.uuid4().hex[:8]}",
        "start_date": stamp.date().isoformat(),
        "start_time": fmt(stamp),
        "expiry_epoch": str(expiry_epoch),
        "expiry": next((e["date"] for e in option_chain().get("expiryData", []) if str(e.get("expiry")) == str(expiry_epoch)), ""),
        "status": "ACTIVE",
        "phase": "STRANGLE",
        "legs": {
            "CE": {"symbol": ce["symbol"], "credit": ce["ltp"], "ltp": ce["ltp"], "high": ce["ltp"], "low": ce["ltp"]},
            "PE": {"symbol": pe["symbol"], "credit": pe["ltp"], "ltp": pe["ltp"], "high": pe["ltp"], "low": pe["ltp"]},
        },
        "initial_credit": initial,
        "realized_points": 0.0,
        "straddle_credit": None,
        "adjustment_count": 0,
        "last_event": reason,
        "last_event_time": fmt(stamp),
        "exit_reason": "",
    }


def load_latest_state() -> dict | None:
    rows = sheet_tab.get_all_values()
    if len(rows) < 2:
        return None
    index = {h: i for i, h in enumerate(rows[0])}
    state_i = index.get("State JSON")
    if state_i is None:
        raise RuntimeError(f"{SHEET_NAME} is missing its State JSON column")
    for row in reversed(rows[1:]):
        if len(row) <= state_i or not row[state_i].strip():
            continue
        try:
            saved = json.loads(row[state_i])
        except json.JSONDecodeError:
            continue
        return saved
    return None


def load_state() -> dict | None:
    # The newest state is authoritative. Never walk backward to an older
    # ACTIVE row after a later row closed that cycle.
    saved = load_latest_state()
    return saved if saved and saved.get("status") == "ACTIVE" else None


def p_and_l(s: dict) -> tuple[float, float, float]:
    open_points = sum(float(leg["credit"]) - float(leg.get("ltp", leg["credit"])) for leg in s["legs"].values())
    net_points = float(s["realized_points"]) + open_points
    return round(open_points, 2), round(net_points, 2), round(net_points * CONTRACT_QTY, 2)


def divergence(s: dict) -> float:
    a = float(s["legs"]["CE"].get("ltp", 0))
    b = float(s["legs"]["PE"].get("ltp", 0))
    high = max(a, b)
    return abs(a - b) / high if high > 0 else 0.0


def snapshot_row(s: dict, event: str = "") -> list:
    stamp = now_ist()
    ce = s["legs"].get("CE", {})
    pe = s["legs"].get("PE", {})
    open_points, net_points, net_rupees = p_and_l(s)
    target_rupees = round(float(s["initial_credit"]) * CONTRACT_QTY * PROFIT_TARGET, 2)
    return [
        s["cycle_id"], fmt(stamp), s["start_date"], s["expiry"], s["status"], s["phase"], current_spot,
        ce.get("symbol", ""), ce.get("credit", ""), ce.get("ltp", ""), ce.get("high", ""), ce.get("low", ""),
        pe.get("symbol", ""), pe.get("credit", ""), pe.get("ltp", ""), pe.get("high", ""), pe.get("low", ""),
        s["initial_credit"], s["realized_points"], open_points, net_points, net_rupees, CONTRACT_QTY, target_rupees,
        round(divergence(s) * 100, 2), s["adjustment_count"], event or s.get("last_event", ""),
        s.get("last_event_time", ""), s.get("exit_reason", ""), json.dumps(s, separators=(",", ":")),
    ]


def record_position_event(
    s: dict, event_type: str, action: str, side: str, symbol: str,
    premium: float, reason: str,
):
    _, _, net_rupees = p_and_l(s)
    log_tab.append_row([
        uuid.uuid4().hex, s.get("cycle_id", ""), fmt(now_ist()), event_type, action, side,
        symbol, s.get("expiry", ""), s.get("phase", ""), round(float(premium), 2),
        CONTRACT_QTY, reason, round(float(s.get("realized_points", 0.0)) * CONTRACT_QTY, 2),
        net_rupees, s.get("status", ""),
    ], value_input_option="RAW")


def log_state(s: dict, event: str = ""):
    global last_write_at
    with state_lock:
        if event:
            s["last_event"] = event
            s["last_event_time"] = fmt(now_ist())
        sheet_tab.append_row(snapshot_row(s, event), value_input_option="RAW")
        last_write_at = now_ist()


def subscribe(symbols: list[str]):
    sock = socket_holder.get("socket")
    if not sock:
        return
    add = [sym for sym in symbols if sym and sym not in subscribed]
    if add:
        sock.subscribe(symbols=add, data_type="SymbolUpdate")
        subscribed.update(add)


def unsubscribe(symbols: list[str]):
    sock = socket_holder.get("socket")
    remove = [sym for sym in symbols if sym in subscribed]
    if sock and remove:
        try:
            sock.unsubscribe(symbols=remove, data_type="SymbolUpdate")
            subscribed.difference_update(remove)
        except Exception as exc:
            print(f"WebSocket unsubscribe warning: {type(exc).__name__}", flush=True)


def close_leg(s: dict, side: str, ltp: float, event: str):
    leg = s["legs"][side]
    s["realized_points"] = round(float(s["realized_points"]) + float(leg["credit"]) - ltp, 4)
    old_symbol = leg["symbol"]
    leg["closed_ltp"] = ltp
    leg["closed_time"] = fmt(now_ist())
    record_position_event(s, "POSITION EXIT", "BUY TO CLOSE", side, old_symbol, ltp, event)
    unsubscribe([old_symbol])
    return old_symbol


def close_cycle(s: dict, reason: str):
    symbols = [leg["symbol"] for leg in s["legs"].values()]
    values = quote(symbols)
    for side, leg in list(s["legs"].items()):
        ltp = values[leg["symbol"]]
        leg["ltp"] = ltp
        close_leg(s, side, ltp, reason)
    s["status"] = "CLOSED"
    s["exit_reason"] = reason
    s["phase"] = "CLOSED"
    log_state(s, reason)


def expiry_after(epoch: str) -> str:
    return expiry_options(option_chain(), epoch)[0]


def start_cycle(after_epoch: str | None, event: str):
    global entry_attempted_date
    data = option_chain()
    if after_epoch is None:
        epoch, _ = expiry_options(data, after_date=now_ist().date())
    else:
        epoch, _ = expiry_options(data, after_epoch)
    contracts = target_contracts(epoch, {"CE": TARGET_PREMIUM, "PE": TARGET_PREMIUM})
    s = make_cycle(epoch, contracts["CE"], contracts["PE"], event)
    for side in ("CE", "PE"):
        leg = s["legs"][side]
        record_position_event(s, "CYCLE ENTRY", "SELL TO OPEN", side, leg["symbol"], leg["ltp"], event)
    if now_ist().weekday() == 1:
        entry_attempted_date = now_ist().date()
    subscribe([contracts["CE"]["symbol"], contracts["PE"]["symbol"]])
    log_state(s, event)
    print(f"Paper cycle {s['cycle_id']} started: expiry {s['expiry']}, CE {contracts['CE']['symbol']} @{contracts['CE']['ltp']:.2f}, PE {contracts['PE']['symbol']} @{contracts['PE']['ltp']:.2f}", flush=True)
    return s


def roll_low_leg(s: dict, reason: str):
    global last_adjustment_at
    if last_adjustment_at and (now_ist() - last_adjustment_at).total_seconds() < 15:
        return
    ce_ltp = float(s["legs"]["CE"].get("ltp", 0))
    pe_ltp = float(s["legs"]["PE"].get("ltp", 0))
    high_side = "CE" if ce_ltp >= pe_ltp else "PE"
    low_side = "PE" if high_side == "CE" else "CE"
    high_ltp = float(s["legs"][high_side]["ltp"])
    low_leg = s["legs"][low_side]
    target = round(high_ltp * REPLACEMENT_RATIO, 2)
    data = option_chain(s["expiry_epoch"])
    candidates = []
    for item in data.get("optionsChain", []):
        if item.get("option_type") != low_side or item.get("symbol") == low_leg["symbol"]:
            continue
        try:
            premium = float(item.get("ltp", item.get("lp")))
        except (TypeError, ValueError):
            continue
        if item.get("symbol") and premium > 0:
            candidates.append((abs(premium - target), item.get("symbol"), premium))
    if not candidates:
        print("Adjustment skipped: no replacement contract found in the same expiry", flush=True)
        return
    _, new_symbol, _ = min(candidates)
    new_ltp = quote([new_symbol])[new_symbol]
    old_symbol = low_leg["symbol"]
    close_leg(s, low_side, float(low_leg["ltp"]), reason)
    s["legs"][low_side] = {"symbol": new_symbol, "credit": new_ltp, "ltp": new_ltp, "high": new_ltp, "low": new_ltp}
    s["adjustment_count"] = int(s["adjustment_count"]) + 1
    s["phase"] = "STRADDLE"
    record_position_event(s, "ADJUSTMENT ENTRY", "SELL TO OPEN", low_side, new_symbol, new_ltp, reason)
    if s.get("straddle_credit") is None:
        # Stop reference is the premium received for the retained high leg
        # plus the replacement leg, not the high leg's market value at roll.
        s["straddle_credit"] = round(float(s["legs"][high_side]["credit"]) + new_ltp, 2)
    subscribe([new_symbol])
    unsubscribe([old_symbol])
    last_adjustment_at = now_ist()
    log_state(s, f"{reason}: closed {low_side}; sold replacement {new_symbol} near 85% of {high_side}")
    print(f"Paper adjustment: {old_symbol} bought back @{low_leg['ltp']:.2f}; {new_symbol} sold @{new_ltp:.2f}; held {high_side} unchanged", flush=True)


def should_roll(s: dict, observed_time: datetime) -> bool:
    if s["status"] != "ACTIVE" or len(s.get("legs", {})) != 2:
        return False
    ratio = divergence(s)
    if observed_time.time() >= ADJUST_TIME and ratio >= EOD_DIVERGENCE:
        return True
    return ratio >= INITIAL_DIVERGENCE


def on_message(message):
    global current_spot
    symbol = message.get("symbol", "")
    try:
        ltp = float(message.get("ltp"))
    except (TypeError, ValueError):
        return
    with state_lock:
        if symbol == UNDERLYING:
            current_spot = round(ltp, 2)
        latest[symbol] = ltp
        if cycle:
            for leg in cycle.get("legs", {}).values():
                if leg.get("symbol") == symbol:
                    leg["ltp"] = ltp
                    leg["high"] = max(float(leg.get("high", ltp)), ltp)
                    leg["low"] = min(float(leg.get("low", ltp)), ltp)


def on_open():
    print("Weekly paper WebSocket connected", flush=True)
    if cycle:
        subscribe([leg["symbol"] for leg in cycle["legs"].values()])
    subscribe([UNDERLYING])
    socket_holder["socket"].keep_running()


def on_close(message):
    print(f"Weekly paper WebSocket closed: {message}", flush=True)


def on_error(message):
    print(f"Weekly paper WebSocket error: {message}", flush=True)


def close_at_end():
    while not stop_event.is_set():
        if now_ist().time() >= END_TIME:
            stop_event.set()
            sock = socket_holder.get("socket")
            if sock:
                try:
                    sock.close_connection()
                except Exception:
                    pass
            return
        time_module.sleep(0.5)


def perform_cycle_exit(reason: str, start_next: bool):
    global cycle, entry_attempted_date
    if not cycle or cycle["status"] != "ACTIVE":
        return
    previous_expiry = cycle["expiry_epoch"]
    close_cycle(cycle, reason)
    if not start_next and now_ist().weekday() == 1:
        entry_attempted_date = now_ist().date()
    if start_next and now_ist().time() < END_TIME:
        cycle = start_cycle(previous_expiry, f"NEW CYCLE AFTER {reason}")
    else:
        cycle = None


def process_tick_actions():
    global cycle, last_write_at
    if not cycle or cycle.get("status") != "ACTIVE":
        return
    stamp = now_ist()
    # Hold positions through the cycle expiry, then roll only this strategy.
    if stamp.date() >= parse_date(cycle["expiry"]) and stamp.time() >= START_TIME:
        perform_cycle_exit("EXPIRY ROLLOVER", True)
        return
    if len(cycle["legs"]) == 2:
        if cycle.get("straddle_credit") and sum(float(leg.get("ltp", 0)) for leg in cycle["legs"].values()) >= float(cycle["straddle_credit"]) * (1 + STRADDLE_STOP):
            perform_cycle_exit("10% STRADDLE COMBINED PREMIUM STOP", False)
            return
        _, net_points, net_rupees = p_and_l(cycle)
        target = float(cycle["initial_credit"]) * CONTRACT_QTY * PROFIT_TARGET
        if net_rupees >= target:
            perform_cycle_exit("80% INITIAL CREDIT NET PROFIT TARGET", True)
            return
        if should_roll(cycle, stamp):
            roll_low_leg(cycle, "15:25 DIVERGENCE" if stamp.time() >= ADJUST_TIME else "50% DIVERGENCE")
            return
    if stamp.minute % SNAPSHOT_MINUTES == 0 and (last_write_at is None or last_write_at.minute != stamp.minute):
        log_state(cycle)


def main():
    global cycle, current_spot, entry_attempted_date
    saved_state = load_latest_state()
    cycle = saved_state if saved_state and saved_state.get("status") == "ACTIVE" else None
    if (
        saved_state
        and saved_state.get("status") == "CLOSED"
        and saved_state.get("last_event_time", "").startswith(now_ist().date().isoformat())
        and "10% STRADDLE" in saved_state.get("exit_reason", "")
        and now_ist().weekday() == 1
    ):
        entry_attempted_date = now_ist().date()
    if cycle:
        print(f"Restored active paper cycle {cycle['cycle_id']} through {cycle['expiry']}", flush=True)
    else:
        print("No active weekly paper cycle found", flush=True)

    # Prepare subscriptions before the market opens; start fresh weekly cycles at 09:30.
    while now_ist().time() < MARKET_OPEN and not stop_event.is_set():
        time_module.sleep(1)
    if cycle:
        subscribe([leg["symbol"] for leg in cycle["legs"].values()])

    sock = data_ws.FyersDataSocket(
        access_token=f"{CLIENT_ID}:{ACCESS_TOKEN}", log_path="", litemode=True,
        write_to_file=False, reconnect=True, on_connect=on_open, on_close=on_close,
        on_error=on_error, on_message=on_message,
    )
    socket_holder["socket"] = sock
    threading.Thread(target=close_at_end, daemon=True).start()
    print("Connecting weekly paper monitor to FYERS market data", flush=True)
    sock.connect()

    while not stop_event.wait(0.5):
        stamp = now_ist()
        if cycle is None and stamp.time() >= START_TIME and stamp.weekday() == 1 and entry_attempted_date != stamp.date():
            # First cycle, or a prior stop exit: Tuesday is the weekly entry day.
            cycle = start_cycle(None, "TUESDAY WEEKLY ENTRY")
        process_tick_actions()
        if stamp.time() >= ADJUST_TIME and cycle and should_roll(cycle, stamp):
            process_tick_actions()

    if cycle and cycle["status"] == "ACTIVE":
        log_state(cycle, "SESSION SNAPSHOT - CARRY FORWARD")
        print("Weekly paper cycle remains active and is saved for the next run", flush=True)


if __name__ == "__main__":
    main()

