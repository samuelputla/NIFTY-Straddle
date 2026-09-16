from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import os
import json
import time as time_module
import threading
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# CONFIGURATION
# ============================================================
CLIENT_ID = "M2DACFCYUO-100"
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
SPREADSHEET_ID = "1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI"
SHEET_NAME = "Sheet1"

IST = ZoneInfo("Asia/Kolkata")
TARGET_TIME = time(9, 30, 0)
EXIT_TIME = time(15, 0, 0)
NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
VIX_SYMBOL = "NSE:INDIAVIX-INDEX"
SL_PERCENTAGES = [10, 15, 20, 25, 30, 35, 40]

# Manual workflow test can set TEST_MODE=true and MONITOR_MINUTES=2.
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
MONITOR_MINUTES = int(os.getenv("MONITOR_MINUTES", "2"))
RUN_TYPE = "MANUAL TEST" if TEST_MODE else "LIVE PAPER"

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS_ACCESS_TOKEN secret is not set")
if not GOOGLE_SERVICE_ACCOUNT_JSON:
    raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is not set")

# ============================================================
# GOOGLE SHEETS
# ============================================================
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
credentials = Credentials.from_service_account_info(
    json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=GOOGLE_SCOPES,
)
gc = gspread.authorize(credentials)
spreadsheet = gc.open_by_key(SPREADSHEET_ID)
sheet = spreadsheet.worksheet(SHEET_NAME)

HEADERS = [
    "Date", "Time", "NIFTY Spot", "India VIX", "ATM", "Expiry",
    "CE Entry", "PE Entry", "CE Symbol", "PE Symbol",
    "CE SL 10%", "CE SL 15%", "CE SL 20%", "CE SL 25%", "CE SL 30%", "CE SL 35%", "CE SL 40%",
    "PE SL 10%", "PE SL 15%", "PE SL 20%", "PE SL 25%", "PE SL 30%", "PE SL 35%", "PE SL 40%",
    "CE LTP", "PE LTP", "CE SL Hit", "PE SL Hit",
    "CE Exit", "PE Exit", "CE Exit Time", "PE Exit Time",
    "CE P&L", "PE P&L", "Total P&L", "Status", "Last Update", "Run Type",
]

# Ensure the complete header row exists. This also extends the headers
# beyond the 24 columns the sheet currently has.
current_headers = sheet.row_values(1)
if current_headers[:len(HEADERS)] != HEADERS:
    sheet.batch_update([
        {"range": f"A1:AL1", "values": [HEADERS]}
    ], value_input_option="RAW")

# ============================================================
# FYERS REST CLIENT
# ============================================================
fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path="",
)

# ============================================================
# HELPERS
# ============================================================
def now_ist():
    return datetime.now(IST)


def fmt_time(dt):
    return dt.strftime("%H:%M:%S")


def update_sheet(row_number, updates):
    """updates = [(column_number, value), ...]"""
    data = []
    for col, value in updates:
        data.append({
            "range": gspread.utils.rowcol_to_a1(row_number, col),
            "values": [[value]],
        })
    if data:
        sheet.batch_update(data, value_input_option="RAW")


def append_entry(row):
    # Append into the next logical row and return its row number.
    existing = sheet.get_all_values()
    row_number = max(2, len(existing) + 1)
    sheet.update(
        f"A{row_number}:AL{row_number}",
        [row],
        value_input_option="RAW",
    )
    return row_number


def get_quote(symbol):
    response = fyers.quotes({"symbols": symbol})
    if response.get("s") != "ok":
        raise RuntimeError(f"Quote failed for {symbol}: {response}")
    return float(response["d"][0]["v"]["lp"])


# ============================================================
# ENTRY TIMING
# ============================================================
print("\n=================================================")
print("NIFTY SHORT STRADDLE - PAPER FORWARD TEST")
print("=================================================")
print(f"Mode         : {RUN_TYPE}")
print("Entry        : 09:30 IST")
print("Exit         : 15:00 IST")
print("Live feed    : FYERS WebSocket SymbolUpdate")
print("Stop levels  : 10%, 15%, 20%, 25%, 30%, 35%, 40%")
print("=================================================")

if not TEST_MODE:
    print("Waiting for 09:30 IST...")
    while now_ist().time() < TARGET_TIME:
        time_module.sleep(1)
else:
    print("TEST MODE: capturing immediately and monitoring briefly.")

capture_time = now_ist()

# ============================================================
# CAPTURE ENTRY
# ============================================================
nifty_spot = get_quote(NIFTY_SYMBOL)
india_vix = get_quote(VIX_SYMBOL)
atm = int((nifty_spot + 25) // 50) * 50

optionchain_response = fyers.optionchain({
    "symbol": NIFTY_SYMBOL,
    "strikecount": 5,
    "timestamp": "",
})
if optionchain_response.get("s") != "ok":
    raise RuntimeError(f"Option chain failed: {optionchain_response}")

chain = optionchain_response["data"]
expiry_data = chain.get("expiryData", [])
if not expiry_data:
    raise RuntimeError("No expiry data returned")
expiry = expiry_data[0]

ce = None
pe = None
for option in chain.get("optionsChain", []):
    if option.get("strike_price") == atm:
        if option.get("option_type") == "CE":
            ce = option
        elif option.get("option_type") == "PE":
            pe = option

if ce is None or pe is None:
    raise RuntimeError(f"ATM contracts not found for {atm}")

ce_symbol = ce["symbol"]
pe_symbol = pe["symbol"]
ce_entry = float(ce["ltp"])
pe_entry = float(pe["ltp"])

ce_sl_values = [round(ce_entry * (1 + p / 100), 2) for p in SL_PERCENTAGES]
pe_sl_values = [round(pe_entry * (1 + p / 100), 2) for p in SL_PERCENTAGES]

print("\nENTRY")
print(f"Time       : {capture_time.strftime('%Y-%m-%d %H:%M:%S')} IST")
print(f"NIFTY      : {nifty_spot:.2f}")
print(f"India VIX  : {india_vix:.2f}")
print(f"ATM        : {atm}")
print(f"Expiry     : {expiry['date']}")
print(f"CE         : {ce_symbol} @ {ce_entry:.2f}")
print(f"PE         : {pe_symbol} @ {pe_entry:.2f}")

row = [
    capture_time.strftime("%Y-%m-%d"),
    capture_time.strftime("%H:%M:%S"),
    round(nifty_spot, 2),
    round(india_vix, 2),
    atm,
    expiry["date"],
    round(ce_entry, 2),
    round(pe_entry, 2),
    ce_symbol,
    pe_symbol,
    *ce_sl_values,
    *pe_sl_values,
    ce_entry,
    pe_entry,
    "NOT HIT",
    "NOT HIT",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "RUNNING",
    capture_time.strftime("%H:%M:%S"),
    RUN_TYPE,
]

row_number = append_entry(row)
print(f"Google Sheet row: {row_number}")

# ============================================================
# LIVE MONITORING STATE
# ============================================================
state = {
    "ce_ltp": ce_entry,
    "pe_ltp": pe_entry,
    "ce_active": True,
    "pe_active": True,
    "ce_hit_levels": set(),
    "pe_hit_levels": set(),
    "ce_exit": None,
    "pe_exit": None,
    "ce_exit_time": None,
    "pe_exit_time": None,
}
state_lock = threading.Lock()
stop_event = threading.Event()
ws_holder = {"socket": None}


def handle_sl(leg, ltp, entry, levels):
    """Record every crossed level; the first crossed level is the paper stop exit."""
    with state_lock:
        state_key = "ce" if leg == "CE" else "pe"
        active_key = f"{state_key}_active"
        hit_key = f"{state_key}_hit_levels"
        exit_key = f"{state_key}_exit"
        exit_time_key = f"{state_key}_exit_time"

        crossed = [p for p, level in zip(SL_PERCENTAGES, levels) if ltp >= level]
        new_crossed = [p for p in crossed if p not in state[hit_key]]
        if new_crossed:
            state[hit_key].update(new_crossed)
            status_text = f"{min(new_crossed)}% HIT @ {ltp:.2f}"
            print(f"\n🚨 {leg} {status_text}")
            status_col = 27 if leg == "CE" else 28
            ltp_col = 25 if leg == "CE" else 26
            update_sheet(row_number, [
                (ltp_col, round(ltp, 2)),
                (status_col, status_text),
                (37, fmt_time(now_ist())),
            ])

        # 10% is the first and therefore actual paper stop. If price jumps
        # over several levels, record all crossed levels but exit this leg
        # at the observed LTP on the first crossing.
        if state[active_key] and crossed:
            state[active_key] = False
            state[exit_key] = ltp
            state[exit_time_key] = now_ist()
            exit_col = 29 if leg == "CE" else 30
            exit_time_col = 31 if leg == "CE" else 32
            update_sheet(row_number, [
                (exit_col, round(ltp, 2)),
                (exit_time_col, fmt_time(state[exit_time_key])),
                (37, fmt_time(now_ist())),
            ])
            print(f"{leg} paper exit @ {ltp:.2f}")


def on_message(message):
    if stop_event.is_set():
        return
    symbol = message.get("symbol", "")
    ltp_raw = message.get("ltp")
    if ltp_raw in (None, ""):
        return
    try:
        ltp = float(ltp_raw)
    except (TypeError, ValueError):
        return

    if symbol == ce_symbol:
        state["ce_ltp"] = ltp
        if state["ce_active"]:
            handle_sl("CE", ltp, ce_entry, ce_sl_values)
    elif symbol == pe_symbol:
        state["pe_ltp"] = ltp
        if state["pe_active"]:
            handle_sl("PE", ltp, pe_entry, pe_sl_values)


def on_error(message):
    print("WebSocket ERROR:", message)


def on_close(message):
    print("WebSocket CLOSED:", message)


def on_open():
    print("\n✅ WebSocket connected")
    print(f"Monitoring: {ce_symbol} + {pe_symbol}")
    ws_holder["socket"].subscribe(
        symbols=[ce_symbol, pe_symbol],
        data_type="SymbolUpdate",
    )
    ws_holder["socket"].keep_running()


def close_at_end(end_dt):
    while not stop_event.is_set():
        if now_ist() >= end_dt:
            stop_event.set()
            sock = ws_holder.get("socket")
            if sock is not None:
                try:
                    if hasattr(sock, "close_connection"):
                        sock.close_connection()
                    elif hasattr(sock, "close"):
                        sock.close()
                except Exception as exc:
                    print("Socket close warning:", exc)
            return
        time_module.sleep(1)


if TEST_MODE:
    monitor_end = now_ist() + timedelta(minutes=max(1, MONITOR_MINUTES))
else:
    today = now_ist().date()
    monitor_end = datetime.combine(today, EXIT_TIME, tzinfo=IST)

# ============================================================
# START WEBSOCKET
# ============================================================
TOKEN = f"{CLIENT_ID}:{ACCESS_TOKEN}"
ws = data_ws.FyersDataSocket(
    access_token=TOKEN,
    log_path="",
    litemode=True,
    write_to_file=False,
    reconnect=True,
    on_connect=on_open,
    on_close=on_close,
    on_error=on_error,
    on_message=on_message,
)
ws_holder["socket"] = ws

threading.Thread(target=close_at_end, args=(monitor_end,), daemon=True).start()

print("\nConnecting to FYERS live feed...")
ws.connect()

# ============================================================
# FINALIZE PAPER EXIT / P&L
# ============================================================
# If a leg did not hit its paper stop, take its 15:00/test-end quote.
# If it already hit, preserve the stop exit price.
if state["ce_exit"] is None:
    try:
        state["ce_exit"] = get_quote(ce_symbol)
    except Exception:
        state["ce_exit"] = state["ce_ltp"]
    state["ce_exit_time"] = now_ist()
if state["pe_exit"] is None:
    try:
        state["pe_exit"] = get_quote(pe_symbol)
    except Exception:
        state["pe_exit"] = state["pe_ltp"]
    state["pe_exit_time"] = now_ist()

ce_pnl = round(ce_entry - state["ce_exit"], 2)
pe_pnl = round(pe_entry - state["pe_exit"], 2)
total_pnl = round(ce_pnl + pe_pnl, 2)

status = "TEST COMPLETE" if TEST_MODE else "COMPLETED"

update_sheet(row_number, [
    (25, round(state["ce_ltp"], 2)),
    (26, round(state["pe_ltp"], 2)),
    (29, round(state["ce_exit"], 2)),
    (30, round(state["pe_exit"], 2)),
    (31, fmt_time(state["ce_exit_time"])),
    (32, fmt_time(state["pe_exit_time"])),
    (33, ce_pnl),
    (34, pe_pnl),
    (35, total_pnl),
    (36, status),
    (37, fmt_time(now_ist())),
])

print("\n=================================================")
print("FINAL PAPER RESULT")
print("=================================================")
print(f"CE Entry : {ce_entry:.2f} | Exit : {state['ce_exit']:.2f} | P&L : {ce_pnl:.2f}")
print(f"PE Entry : {pe_entry:.2f} | Exit : {state['pe_exit']:.2f} | P&L : {pe_pnl:.2f}")
print(f"TOTAL P&L: {total_pnl:.2f}")
print(f"Sheet row: {row_number}")
print(f"Status   : {status}")
print("=================================================")
