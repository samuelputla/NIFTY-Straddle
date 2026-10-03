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

# Keep the existing Sheet1 history intact. Each stop-loss scenario is written
# as its own row in a dedicated worksheet.
SCENARIO_SHEET_NAME = "SL_Scenarios"
SCENARIO_HEADERS = [
    "Date", "Entry Time", "NIFTY Spot", "India VIX", "ATM", "Expiry", "SL %",
    "CE Symbol", "PE Symbol", "CE Entry", "CE Stop Price", "CE SL Hit",
    "CE Hit Time", "CE Exit Price", "CE Exit Time", "CE Exit Reason", "CE P&L",
    "PE Entry", "PE Stop Price", "PE SL Hit", "PE Hit Time", "PE Exit Price",
    "PE Exit Time", "PE Exit Reason", "PE P&L", "Total P&L", "Status",
    "Last Update", "Run Type",
]

worksheet_titles = {worksheet.title for worksheet in spreadsheet.worksheets()}
if SCENARIO_SHEET_NAME in worksheet_titles:
    scenario_sheet = spreadsheet.worksheet(SCENARIO_SHEET_NAME)
else:
    scenario_sheet = spreadsheet.add_worksheet(
        title=SCENARIO_SHEET_NAME,
        rows=1000,
        cols=len(SCENARIO_HEADERS),
    )

current_scenario_headers = scenario_sheet.row_values(1)
if not current_scenario_headers:
    scenario_sheet.update(
        range_name="A1:AC1",
        values=[SCENARIO_HEADERS],
        value_input_option="RAW",
    )
elif current_scenario_headers[:len(SCENARIO_HEADERS)] != SCENARIO_HEADERS:
    raise RuntimeError(
        f"Unexpected headers in {SCENARIO_SHEET_NAME}; refusing to overwrite them"
    )

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


def make_scenario_row(percent):
    scenario = state["scenarios"][percent]
    index = SL_PERCENTAGES.index(percent)
    ce_exit = scenario["ce_exit"]
    pe_exit = scenario["pe_exit"]
    ce_pnl = round(ce_entry - ce_exit, 2) if ce_exit is not None else ""
    pe_pnl = round(pe_entry - pe_exit, 2) if pe_exit is not None else ""
    total_pnl = round(ce_pnl + pe_pnl, 2) if ce_pnl != "" and pe_pnl != "" else ""
    status = "TEST COMPLETE" if state["complete"] and TEST_MODE else (
        "COMPLETED" if state["complete"] else "RUNNING"
    )
    return [
        capture_time.strftime("%Y-%m-%d"),
        capture_time.strftime("%H:%M:%S"),
        round(nifty_spot, 2),
        round(india_vix, 2),
        atm,
        expiry["date"],
        percent,
        ce_symbol,
        pe_symbol,
        round(ce_entry, 2),
        ce_sl_values[index],
        "HIT" if scenario["ce_hit"] else "NOT HIT",
        fmt_time(scenario["ce_hit_time"]) if scenario["ce_hit_time"] else "",
        round(ce_exit, 2) if ce_exit is not None else "",
        fmt_time(scenario["ce_exit_time"]) if scenario["ce_exit_time"] else "",
        scenario["ce_exit_reason"],
        ce_pnl,
        round(pe_entry, 2),
        pe_sl_values[index],
        "HIT" if scenario["pe_hit"] else "NOT HIT",
        fmt_time(scenario["pe_hit_time"]) if scenario["pe_hit_time"] else "",
        round(pe_exit, 2) if pe_exit is not None else "",
        fmt_time(scenario["pe_exit_time"]) if scenario["pe_exit_time"] else "",
        scenario["pe_exit_reason"],
        pe_pnl,
        total_pnl,
        status,
        fmt_time(now_ist()),
        RUN_TYPE,
    ]


def update_scenario_rows(percentages):
    updates = []
    for percent in sorted(set(percentages)):
        row_number = scenario_row_numbers[percent]
        updates.append({
            "range": f"A{row_number}:AC{row_number}",
            "values": [make_scenario_row(percent)],
        })
    if updates:
        scenario_sheet.batch_update(updates, value_input_option="RAW")


def append_scenario_rows(rows):
    existing = scenario_sheet.get_all_values()
    first_row = max(2, len(existing) + 1)
    last_row = first_row + len(rows) - 1
    scenario_sheet.update(
        range_name=f"A{first_row}:AC{last_row}",
        values=rows,
        value_input_option="RAW",
    )
    return first_row


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

# ============================================================
# INDEPENDENT PAPER SCENARIOS
# ============================================================
state = {
    "ce_ltp": ce_entry,
    "pe_ltp": pe_entry,
    "complete": False,
    "scenarios": {},
}
for percent in SL_PERCENTAGES:
    state["scenarios"][percent] = {
        "ce_hit": False,
        "ce_hit_time": None,
        "ce_exit": None,
        "ce_exit_time": None,
        "ce_exit_reason": "",
        "pe_hit": False,
        "pe_hit_time": None,
        "pe_exit": None,
        "pe_exit_time": None,
        "pe_exit_reason": "",
    }

scenario_rows = [make_scenario_row(percent) for percent in SL_PERCENTAGES]
scenario_first_row = append_scenario_rows(scenario_rows)
scenario_row_numbers = {
    percent: scenario_first_row + index
    for index, percent in enumerate(SL_PERCENTAGES)
}
print(f"Google Sheet {SCENARIO_SHEET_NAME} rows: {scenario_first_row}-{scenario_first_row + len(SL_PERCENTAGES) - 1}")

state_lock = threading.Lock()
stop_event = threading.Event()
ws_holder = {"socket": None}


def handle_sl(leg, ltp):
    """Track each stop percentage independently for the specified option leg."""
    leg_key = "ce" if leg == "CE" else "pe"
    sl_values = ce_sl_values if leg_key == "ce" else pe_sl_values
    changed_percentages = []
    observed_at = now_ist()

    with state_lock:
        state[f"{leg_key}_ltp"] = ltp
        for percent, stop_price in zip(SL_PERCENTAGES, sl_values):
            scenario = state["scenarios"][percent]
            hit_key = f"{leg_key}_hit"
            if not scenario[hit_key] and ltp >= stop_price:
                scenario[hit_key] = True
                scenario[f"{leg_key}_hit_time"] = observed_at
                scenario[f"{leg_key}_exit"] = ltp
                scenario[f"{leg_key}_exit_time"] = observed_at
                scenario[f"{leg_key}_exit_reason"] = "STOP LOSS"
                changed_percentages.append(percent)

    if changed_percentages:
        levels_text = ", ".join(f"{percent}%" for percent in changed_percentages)
        print(f"\n🚨 {leg} stop scenario(s) hit: {levels_text} @ {ltp:.2f}")
        update_scenario_rows(changed_percentages)


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
        handle_sl("CE", ltp)
    elif symbol == pe_symbol:
        handle_sl("PE", ltp)


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
# FINALIZE EACH PAPER SCENARIO
# ============================================================
# Every unhit leg/scenario exits independently at the 15:00 or test-end quote.
final_ce_ltp = state["ce_ltp"]
final_pe_ltp = state["pe_ltp"]
try:
    final_ce_ltp = get_quote(ce_symbol)
except Exception as exc:
    print("CE final quote warning; using last WebSocket price:", exc)
try:
    final_pe_ltp = get_quote(pe_symbol)
except Exception as exc:
    print("PE final quote warning; using last WebSocket price:", exc)

final_time = now_ist()
final_reason = "TEST END" if TEST_MODE else "15:00 EXIT"
with state_lock:
    for percent in SL_PERCENTAGES:
        scenario = state["scenarios"][percent]
        if scenario["ce_exit"] is None:
            scenario["ce_exit"] = final_ce_ltp
            scenario["ce_exit_time"] = final_time
            scenario["ce_exit_reason"] = final_reason
        if scenario["pe_exit"] is None:
            scenario["pe_exit"] = final_pe_ltp
            scenario["pe_exit_time"] = final_time
            scenario["pe_exit_reason"] = final_reason
    state["complete"] = True
    update_scenario_rows(SL_PERCENTAGES)

print("\n=================================================")
print("FINAL PAPER RESULTS BY STOP-LOSS SCENARIO")
print("=================================================")
for percent in SL_PERCENTAGES:
    scenario = state["scenarios"][percent]
    ce_pnl = round(ce_entry - scenario["ce_exit"], 2)
    pe_pnl = round(pe_entry - scenario["pe_exit"], 2)
    total_pnl = round(ce_pnl + pe_pnl, 2)
    print(
        f"{percent:>2}% SL | "
        f"CE exit {scenario['ce_exit']:.2f} ({scenario['ce_exit_reason']}) "
        f"P&L {ce_pnl:.2f} | "
        f"PE exit {scenario['pe_exit']:.2f} ({scenario['pe_exit_reason']}) "
        f"P&L {pe_pnl:.2f} | Total {total_pnl:.2f}"
    )
print(f"Google Sheet tab: {SCENARIO_SHEET_NAME}")
print("=================================================")
