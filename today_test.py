from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import json
import os
import sys
import threading
from request_timing import start_request, run_with_timeout, collect_ready_requests
import time as time_module

import gspread
from google.oauth2.service_account import Credentials

# Paper monitoring only. This program intentionally contains no order API calls.
CLIENT_ID = "M2DACFCYUO-100"
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
SPREADSHEET_ID = "1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI"

IST = ZoneInfo("Asia/Kolkata")
TARGET_TIME = time(9, 30)
EXIT_TIME = time(15, 0)
SL_PERCENTAGES = [10, 15, 20, 25, 30, 35, 40]
CONTRACT_QTY = 65
ROUND_TRIP_CHARGES_RUPEES = 150
NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
VIX_SYMBOL = "NSE:INDIAVIX-INDEX"
SCENARIO_SHEET_NAME = "Nifty Daily Straddle Logs"
DAILY_SHEET_NAME = "Nifty Daily straddle"

TEST_MODE = os.getenv("TEST_MODE", "false").strip().lower() == "true"
SETUP_ONLY = os.getenv("SETUP_ONLY", "false").strip().lower() == "true"
MONITOR_MINUTES = max(1, int(os.getenv("MONITOR_MINUTES", "2")))
RUN_TYPE = "MANUAL TEST" if TEST_MODE else "SCHEDULED PAPER"

SCENARIO_HEADERS = [
    "Date", "Entry Time", "NIFTY Spot", "India VIX", "ATM", "Expiry", "SL %",
    "CE Symbol", "PE Symbol", "CE Entry", "CE Stop Price", "CE SL Hit",
    "CE Hit Time", "CE Exit Price", "CE Exit Time", "CE Exit Reason", "CE P&L",
    "PE Entry", "PE Stop Price", "PE SL Hit", "PE Hit Time", "PE Exit Price",
    "PE Exit Time", "PE Exit Reason", "PE P&L", "Total P&L", "Status",
    "Last Update", "Run Type",
]
DAILY_HEADERS = [
    "Date",
    "Vix at 09:30 AM",
    "Prev. Day High",
    "Prev. Day Low",
    "Prev. Day closing",
    "Day Opening",
    "Gap up/Gap Down",
    "CE IO",
    "PE IO",
    "PE/CE",
    "Market Bias",
    "Strike",
    "Expiry",
    "CE Entry Price",
    "PE Entry Price",
    "Day CE High Premium",
    "Day CE Low Premium",
    "Day PE High Premium",
    "Day PE Low Premium",
    "CE Exit Price",
    "PE Exit Price",
    *[f"{p}% Profit" for p in SL_PERCENTAGES],
    *[f"{p}% CE Net" for p in SL_PERCENTAGES],
    *[f"{p}% PE Net" for p in SL_PERCENTAGES],
    *[f"{p}% CE SL" for p in SL_PERCENTAGES],
    *[f"{p}% PE SL" for p in SL_PERCENTAGES],
    "Entry Quote Request Started At (IST)",
    "Entry Snapshot Retrieved At (IST)",
    "CE LTP Last Trade Time (IST)",
    "PE LTP Last Trade Time (IST)",
    "OI Snapshot Retrieved At (IST)",
    "OI Snapshot Status",
    "OI Strike Scope",
    "Entry Data Status",
    "Run Status",
    "VIX Snapshot Retrieved At (IST)",
]

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
if not GOOGLE_SERVICE_ACCOUNT_JSON:
    raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is not set")

credentials = Credentials.from_service_account_info(
    json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
    scopes=GOOGLE_SCOPES,
)
gc = gspread.authorize(credentials)
gc.set_timeout((3, 8))
spreadsheet = gc.open_by_key(SPREADSHEET_ID)


def ensure_worksheet(title, headers, rows=1000):
    titles = {item.title for item in spreadsheet.worksheets()}
    if title in titles:
        sheet = spreadsheet.worksheet(title)
    else:
        sheet = spreadsheet.add_worksheet(
            title=title,
            rows=rows,
            cols=len(headers),
        )

    existing_values = sheet.get_all_values()
    existing_headers = existing_values[0] if existing_values else []
    if not existing_headers:
        last_col = column_letter(len(headers))
        sheet.update(
            range_name=f"A1:{last_col}1",
            values=[headers],
            value_input_option="RAW",
        )
    elif existing_headers != headers:
        has_data_rows = any(
            any(str(cell).strip() for cell in row)
            for row in existing_values[1:]
        )
        if len(existing_headers) < len(headers) and existing_headers == headers[:len(existing_headers)]:
            # Append new columns without changing historical cells; old rows stay blank there.
            sheet.resize(
                rows=max(sheet.row_count, len(existing_values)),
                cols=max(sheet.col_count, len(headers)),
            )
            last_col = column_letter(len(headers))
            sheet.update(
                range_name=f"A1:{last_col}1",
                values=[headers],
                value_input_option="RAW",
            )
        elif len(existing_headers) == len(headers) and not has_data_rows:
            # Safe schema-label migration while a sheet contains headers only.
            last_col = column_letter(len(headers))
            sheet.update(
                range_name=f"A1:{last_col}1",
                values=[headers],
                value_input_option="RAW",
            )
        else:
            raise RuntimeError(
                f"Unexpected headers in {title}; refusing to change existing data"
            )
    return sheet


def column_letter(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


scenario_sheet = ensure_worksheet(
    SCENARIO_SHEET_NAME,
    SCENARIO_HEADERS,
    rows=1000,
)
daily_sheet = ensure_worksheet(
    DAILY_SHEET_NAME,
    DAILY_HEADERS,
    rows=1000,
)

if SETUP_ONLY:
    print(f"Google Sheets tabs ready: {SCENARIO_SHEET_NAME}, {DAILY_SHEET_NAME}")
    sys.exit(0)

if not ACCESS_TOKEN:
    raise RuntimeError("FYERS_ACCESS_TOKEN secret is not set")

fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path="",
)


def now_ist():
    return datetime.now(IST)


def fmt_time(value):
    return value.strftime("%H:%M:%S") if value else ""


def call_fyers(method, payload):
    # Isolate concurrent SDK requests and bound even the SDK's internal retries.
    def request():
        client = fyersModel.FyersModel(
            client_id=CLIENT_ID, token=ACCESS_TOKEN,
            is_async=False, log_path="",
        )
        return getattr(client, method)(payload)
    return run_with_timeout(request, 6)


def market_timestamp(value):
    """Convert FYERS quote 'tt' epoch seconds/milliseconds to India time."""
    if value in (None, ""):
        return None
    try:
        epoch = float(value)
        if epoch <= 0:
            return None
        if epoch > 10_000_000_000:
            epoch /= 1000
        return datetime.fromtimestamp(epoch, IST)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def get_optionchain_spot_quote():
    """Build an index spot quote from FYERS' option-chain underlying entry."""
    response = call_fyers("optionchain", {
        "symbol": NIFTY_SYMBOL,
        "strikecount": 50,
        "timestamp": "",
    })
    if response.get("s") != "ok":
        raise RuntimeError(
            f"NIFTY option-chain fallback failed: "
            f"{response.get('code')} {response.get('message', '')}"
        )

    chain = response.get("data", {}).get("optionsChain", [])
    underlying = next(
        (
            item for item in chain
            if item.get("option_type") in (None, "")
            or item.get("strike_price") == -1
        ),
        None,
    )
    if underlying is None:
        raise RuntimeError("FYERS option chain did not include the NIFTY spot entry")

    try:
        spot = float(underlying.get("ltp", underlying.get("lp")))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("FYERS option-chain spot entry has no valid LTP") from exc
    if spot <= 0:
        raise RuntimeError(f"FYERS option-chain returned invalid NIFTY spot: {spot}")

    # The option-chain spot entry may not carry quote OHLC/volume fields.
    return {
        NIFTY_SYMBOL: {
            "lp": spot,
            "open_price": underlying.get("open_price", 0),
        }
    }


def get_quotes(symbols):
    # NIFTY's quotes endpoint stalled for 16 minutes on 14 Oct. The
    # option-chain underlying supplies spot without that failing route.
    if symbols == [NIFTY_SYMBOL]:
        return get_optionchain_spot_quote()
    response = call_fyers("quotes", {"symbols": ",".join(symbols)})
    if response.get("s") != "ok":
        code = response.get("code")
        if len(symbols) > 1 and code in (-99, "-99"):
            print(
                "FYERS rejected batched quotes; retrying one symbol at a time.",
                flush=True,
            )
            combined = {}
            for symbol in symbols:
                combined.update(get_quotes([symbol]))
            return combined
        if symbols == [NIFTY_SYMBOL] and code in (-99, "-99"):
            print(
                "FYERS rejected the NIFTY quote request; using the "
                "NIFTY spot from its option chain.",
                flush=True,
            )
            return get_optionchain_spot_quote()
        raise RuntimeError(
            f"Quotes failed for {symbols}: "
            f"code {code}, {response.get('message', 'unknown error')}"
        )
    result = {}
    for item in response.get("d", []):
        values = item.get("v", {})
        symbol = item.get("n") or values.get("symbol")
        if not symbol:
            continue
        result[symbol] = values
    missing = [symbol for symbol in symbols if symbol not in result]
    if missing:
        raise RuntimeError(f"Quotes missing symbols: {missing}")
    return result


def ltp_from_quote(values, label):
    try:
        price = float(values["lp"])
        if not 0 < price < float("inf"):
            raise ValueError("non-positive or non-finite LTP")
        return price
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid {label} LTP in quote: {values}") from exc



def get_previous_day_ohlc(today):
    start = (today - timedelta(days=10)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    response = call_fyers("history", {
        "symbol": NIFTY_SYMBOL,
        "resolution": "D",
        "date_format": "1",
        "range_from": start,
        "range_to": end,
        "cont_flag": "1",
    })
    if response.get("s") != "ok":
        raise RuntimeError(f"NIFTY daily history failed: {response}")

    prior = []
    for candle in response.get("candles", []):
        if len(candle) < 5:
            continue
        candle_date = datetime.fromtimestamp(float(candle[0]), IST).date()
        if candle_date < today:
            prior.append((candle_date, candle))

    if not prior:
        raise RuntimeError("No previous trading-day NIFTY candle was returned")

    _, candle = max(prior, key=lambda item: item[0])
    return {
        "date": datetime.fromtimestamp(float(candle[0]), IST).date(),
        "high": float(candle[2]),
        "low": float(candle[3]),
        "close": float(candle[4]),
    }


def nearest_atm(spot):
    return int((spot + 25) // 50) * 50


def get_atm_options(chain_response, atm):
    chain = chain_response["data"]
    expiries = chain.get("expiryData", [])
    if not expiries:
        raise RuntimeError("No expiry data returned by FYERS")
    expiry = expiries[0]

    ce = pe = None
    for option in chain.get("optionsChain", []):
        if option.get("strike_price") != atm:
            continue
        if option.get("option_type") == "CE":
            ce = option
        elif option.get("option_type") == "PE":
            pe = option
    if ce is None or pe is None:
        raise RuntimeError(f"ATM CE/PE contracts not found for strike {atm}")
    return chain, expiry, ce, pe


def make_scenario_row(percent):
    scenario = state["scenarios"][percent]
    index = SL_PERCENTAGES.index(percent)
    ce_exit = scenario["ce_exit"]
    pe_exit = scenario["pe_exit"]
    ce_net = round(ce_entry - ce_exit, 2) if ce_exit is not None else ""
    pe_net = round(pe_entry - pe_exit, 2) if pe_exit is not None else ""
    total_net = round(ce_net + pe_net, 2) if ce_net != "" and pe_net != "" else ""
    status = "COMPLETED" if state["complete"] else "RUNNING"
    return [
        capture_time.strftime("%Y-%m-%d"),
        capture_time.strftime("%H:%M:%S"),
        round(nifty_spot, 2),
        round(india_vix, 2) if india_vix is not None else "",
        atm,
        expiry["date"],
        percent,
        ce_symbol,
        pe_symbol,
        round(ce_entry, 2),
        ce_sl_values[index],
        "HIT" if scenario["ce_hit"] else "NOT HIT",
        fmt_time(scenario["ce_hit_time"]),
        round(ce_exit, 2) if ce_exit is not None else "",
        fmt_time(scenario["ce_exit_time"]),
        scenario["ce_exit_reason"],
        ce_net,
        round(pe_entry, 2),
        pe_sl_values[index],
        "HIT" if scenario["pe_hit"] else "NOT HIT",
        fmt_time(scenario["pe_hit_time"]),
        round(pe_exit, 2) if pe_exit is not None else "",
        fmt_time(scenario["pe_exit_time"]),
        scenario["pe_exit_reason"],
        pe_net,
        total_net,
        status,
        fmt_time(now_ist()),
        RUN_TYPE,
    ]


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


def update_scenario_rows(percentages):
    updates = []
    with state_lock:
        for percent in sorted(set(percentages)):
            row_number = scenario_row_numbers[percent]
            updates.append({
                "range": f"A{row_number}:AC{row_number}",
                "values": [make_scenario_row(percent)],
            })
    if updates:
        scenario_sheet.batch_update(updates, value_input_option="RAW")


def daily_bias(put_oi, call_oi):
    if not call_oi:
        return "", "N/A"
    ratio = round(put_oi / call_oi, 4)
    # Preserve the user's requested custom label convention.
    bias = "Bearish" if ratio < 1 else "Bullish" if ratio > 1 else "Neutral"
    return ratio, bias


def sl_cell(scenario, leg, stop_price):
    if scenario[f"{leg}_hit"]:
        hit_time = fmt_time(scenario[f"{leg}_hit_time"])
        observed = scenario[f"{leg}_trigger_ltp"]
        return f"HIT @ {stop_price:.2f}; observed {observed:.2f} at {hit_time}"
    return f"NOT HIT; level {stop_price:.2f}"


def make_daily_row(run_status):
    scenario_nets = {}
    for percent in SL_PERCENTAGES:
        scenario = state["scenarios"][percent]
        ce_exit = scenario["ce_exit"]
        pe_exit = scenario["pe_exit"]
        ce_net = round(ce_entry - ce_exit, 2) if ce_exit is not None else ""
        pe_net = round(pe_entry - pe_exit, 2) if pe_exit is not None else ""
        total = (
            round((ce_net + pe_net) * CONTRACT_QTY - ROUND_TRIP_CHARGES_RUPEES, 2)
            if ce_net != "" and pe_net != ""
            else ""
        )
        scenario_nets[percent] = (total, ce_net, pe_net)

    values = [
        capture_time.strftime("%Y-%m-%d"),
        round(india_vix, 2) if india_vix is not None else "",
        previous_ohlc["high"],
        previous_ohlc["low"],
        previous_ohlc["close"],
        day_open,
        gap_text,
        call_oi,
        put_oi,
        pcr,
        market_bias,
        atm,
        expiry["date"],
        round(ce_entry, 2),
        round(pe_entry, 2),
        round(state["ce_high"], 2),
        round(state["ce_low"], 2),
        round(state["pe_high"], 2),
        round(state["pe_low"], 2),
        round(state["final_ce_ltp"], 2)
        if state["final_ce_ltp"] is not None else "",
        round(state["final_pe_ltp"], 2)
        if state["final_pe_ltp"] is not None else "",
    ]
    values.extend(scenario_nets[p][0] for p in SL_PERCENTAGES)
    values.extend(scenario_nets[p][1] for p in SL_PERCENTAGES)
    values.extend(scenario_nets[p][2] for p in SL_PERCENTAGES)
    values.extend(
        sl_cell(state["scenarios"][p], "ce", ce_sl_values[i])
        for i, p in enumerate(SL_PERCENTAGES)
    )
    values.extend(
        sl_cell(state["scenarios"][p], "pe", pe_sl_values[i])
        for i, p in enumerate(SL_PERCENTAGES)
    )
    values.extend([
        fmt_time(quote_request_started_at),
        capture_time.strftime("%Y-%m-%d %H:%M:%S"),
        fmt_time(ce_trade_time),
        fmt_time(pe_trade_time),
        fmt_time(oi_retrieved_at),
        oi_snapshot_status,
        "FYERS option chain aggregate OI for returned strike range",
        entry_data_status + f"; VIX {vix_snapshot_status}",
        run_status,
        vix_retrieved_at.strftime("%Y-%m-%d %H:%M:%S") if vix_retrieved_at else "",
    ])
    return values


def write_daily_row(run_status):
    last_col = column_letter(len(DAILY_HEADERS))
    with state_lock:
        values = make_daily_row(run_status)
    daily_sheet.update(
        range_name=f"A{daily_row_number}:{last_col}{daily_row_number}",
        values=[values],
        value_input_option="RAW",
    )


def create_daily_row_for_today():
    values = daily_sheet.get_all_values()
    today_text = now_ist().date().strftime("%Y-%m-%d")
    for row_number, row in enumerate(values[1:], start=2):
        if row and row[0] == today_text:
            raise RuntimeError(
                f"{DAILY_SHEET_NAME} already has a row for {today_text}; "
                "refusing to create a duplicate run"
            )
    blank = [""] * len(DAILY_HEADERS)
    blank[0] = today_text
    blank[DAILY_HEADERS.index("Run Status")] = "MISSED 09:30 CAPTURE"
    daily_sheet.append_row(blank, value_input_option="RAW")


def update_summary_after_event(percentages):
    # Persist on the main thread; the socket must keep processing stop ticks.
    with state_lock:
        pending_scenario_updates.update(percentages)


def handle_sl(leg, ltp):
    leg_key = "ce" if leg == "CE" else "pe"
    if stop_event.is_set():
        return

    observed_at = now_ist()
    sl_values = ce_sl_values if leg_key == "ce" else pe_sl_values
    changed = []
    with state_lock:
        if stop_event.is_set() or observed_at >= target_end:
            return
        state[f"{leg_key}_ltp"] = ltp
        state[f"{leg_key}_last_tick"] = observed_at
        high_key = f"{leg_key}_high"
        low_key = f"{leg_key}_low"
        state[high_key] = max(state[high_key], ltp)
        state[low_key] = min(state[low_key], ltp)

        for percent, stop_price in zip(SL_PERCENTAGES, sl_values):
            scenario = state["scenarios"][percent]
            hit_key = f"{leg_key}_hit"
            if not scenario[hit_key] and ltp >= stop_price:
                scenario[hit_key] = True
                scenario[f"{leg_key}_hit_time"] = observed_at
                # Paper fills use the stop threshold, per the user's example.
                # The observed crossing tick remains logged separately.
                scenario[f"{leg_key}_exit"] = stop_price
                scenario[f"{leg_key}_trigger_ltp"] = ltp
                scenario[f"{leg_key}_exit_time"] = observed_at
                scenario[f"{leg_key}_exit_reason"] = "STOP LOSS"
                changed.append(percent)

    if changed:
        levels = ", ".join(f"{p}%" for p in changed)
        print(f"\n{leg} stop scenario(s) hit: {levels} @ {ltp:.2f}")
        update_summary_after_event(changed)


def on_message(message):
    if stop_event.is_set():
        return
    symbol = message.get("symbol", "")
    raw_ltp = message.get("ltp")
    try:
        ltp = float(raw_ltp)
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
    print("\nWebSocket connected")
    print(f"Monitoring paper prices: {ce_symbol} + {pe_symbol}")
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
        time_module.sleep(0.25)


# ============================================================
# PREPARE CONTRACTS BEFORE 09:30, THEN CAPTURE ENTRY QUOTES
# ============================================================
today = now_ist().date()
print("Fetching previous market-day NIFTY values...", flush=True)
previous_ohlc = get_previous_day_ohlc(today)
print(
    f"Previous market-day candle loaded for {previous_ohlc['date']}.",
    flush=True,
)
daily_row_number = None
if not TEST_MODE:
    summary_rows = daily_sheet.get_all_values()
    today_text = today.strftime("%Y-%m-%d")
    for row_number, row in enumerate(summary_rows[1:], start=2):
        if row and row[0] == today_text:
            raise RuntimeError(
                f"{DAILY_SHEET_NAME} already has a row for {today_text}; "
                "refusing to duplicate the day's straddle"
            )
    daily_row_number = len(summary_rows) + 1


target_dt = datetime.combine(today, TARGET_TIME, tzinfo=IST)
prep_dt = target_dt - timedelta(minutes=5)
entry_deadline = datetime.combine(today, EXIT_TIME, tzinfo=IST)
if not TEST_MODE and now_ist() >= entry_deadline:
    print("Market monitoring window has ended; no new daily entry will be created.")
    sys.exit(0)

if not TEST_MODE:
    print("Preparing NIFTY/VIX and option contracts before 09:30 IST...")
    while now_ist() < prep_dt:
        time_module.sleep(0.25)
else:
    print("TEST MODE: preparing and capturing immediately.")

# Select the ATM strike and expiry using NIFTY spot only; VIX has no strike selection.
print("Preparing ATM contracts from the option-chain underlying...", flush=True)
while True:
    try:
        optionchain_response = call_fyers("optionchain", {
            "symbol": NIFTY_SYMBOL, "strikecount": 50, "timestamp": "",
        })
        if optionchain_response.get("s") != "ok":
            raise RuntimeError("Option-chain preparation failed")
        underlying = next(item for item in optionchain_response["data"]["optionsChain"]
                          if item.get("strike_price") == -1 or item.get("option_type") in (None, ""))
        preselection_nifty_values = {
            "lp": underlying.get("ltp", underlying.get("lp")),
            "open_price": underlying.get("open_price", 0),
        }
        preselection_nifty = ltp_from_quote(preselection_nifty_values, "NIFTY")
        atm = nearest_atm(preselection_nifty)
        # Validate before leaving the bounded preparation retry loop.
        get_atm_options(optionchain_response, atm)
        break
    except Exception as exc:
        print(f"Contract preparation retry: {type(exc).__name__}", flush=True)
        if TEST_MODE or now_ist() >= entry_deadline:
            raise
        time_module.sleep(1)

chain, expiry, ce, pe = get_atm_options(optionchain_response, atm)
ce_symbol = ce["symbol"]
pe_symbol = pe["symbol"]
oi_retrieved_at = now_ist()
oi_snapshot_status = "PRE-ENTRY CONTRACT-SELECTION SNAPSHOT"
call_oi = int(chain.get("callOi", 0) or 0)
put_oi = int(chain.get("putOi", 0) or 0)
pcr, market_bias = daily_bias(put_oi, call_oi)

if not TEST_MODE:
    # Refresh the five-minute preparation just before entry, with enough room
    # for the bounded chain request to finish before 09:30.
    refresh_dt = target_dt - timedelta(seconds=10)
    while now_ist() < refresh_dt:
        time_module.sleep(0.05)
    try:
        response = call_fyers("optionchain", {
            "symbol": NIFTY_SYMBOL, "strikecount": 50, "timestamp": "",
        })
        if response.get("s") != "ok":
            raise RuntimeError("Pre-entry contract refresh failed")
        spot_item = next(item for item in response["data"]["optionsChain"]
                         if item.get("strike_price") == -1 or item.get("option_type") in (None, ""))
        spot_quote = {"lp": spot_item.get("ltp", spot_item.get("lp")),
                      "open_price": spot_item.get("open_price", 0)}
        refreshed_atm = nearest_atm(ltp_from_quote(spot_quote, "NIFTY"))
        refreshed_chain, refreshed_expiry, refreshed_ce, refreshed_pe = get_atm_options(response, refreshed_atm)
        chain, expiry, ce, pe = refreshed_chain, refreshed_expiry, refreshed_ce, refreshed_pe
        atm, preselection_nifty_values = refreshed_atm, spot_quote
        ce_symbol, pe_symbol = ce["symbol"], pe["symbol"]
        call_oi, put_oi = int(chain.get("callOi", 0) or 0), int(chain.get("putOi", 0) or 0)
        pcr, market_bias = daily_bias(put_oi, call_oi)
        oi_retrieved_at = now_ist()
    except Exception as exc:
        print(f"Pre-entry refresh unavailable: {type(exc).__name__}; retaining prepared contracts", flush=True)
    print("Waiting for the 09:30 IST entry quote...")
    while now_ist() < target_dt:
        time_module.sleep(0.05)
    quote_request_started_at = now_ist()
    late_seconds = (quote_request_started_at - target_dt).total_seconds()
    if late_seconds > 5: print(f"Late capture; continuing at {fmt_time(quote_request_started_at)} IST")
else:
    quote_request_started_at = now_ist()

def refresh_optionchain_for_oi():
    # Use a separate client because this request runs alongside the 09:30 quote requests.
    oi_client = fyersModel.FyersModel(
        client_id=CLIENT_ID,
        token=ACCESS_TOKEN,
        is_async=False,
        log_path="",
    )
    return run_with_timeout(oi_client.optionchain, 6, {
        "symbol": NIFTY_SYMBOL,
        "strikecount": 50,
        "timestamp": "",
    })


# Capture the first usable CE/PE pair; ancillary metadata cannot delay the
# recorded premium timestamp or make executor shutdown wait indefinitely.
def timestamped_metadata(function, *args):
    value = function(*args)
    return value, now_ist()


metadata_requests = {
    "VIX": start_request(timestamped_metadata, get_quotes, [VIX_SYMBOL]),
    "OI": start_request(timestamped_metadata, refresh_optionchain_for_oi),
}
metadata_deadline = time_module.monotonic() + 15
while True:
    try:
        entry_snapshot = get_quotes([ce_symbol, pe_symbol])
        ltp_from_quote(entry_snapshot[ce_symbol], "CE")
        ltp_from_quote(entry_snapshot[pe_symbol], "PE")
        capture_time = now_ist()
        if not TEST_MODE and capture_time >= entry_deadline:
            raise RuntimeError("No usable entry pair before the daily close")
        break
    except Exception as exc:
        print(f"Entry quote retry: {type(exc).__name__}", flush=True)
        if TEST_MODE or now_ist() >= entry_deadline:
            raise
        time_module.sleep(1)

entry_snapshot[NIFTY_SYMBOL] = preselection_nifty_values
# Supporting data is applied only after monitoring has started.
india_vix = None
vix_retrieved_at = None
vix_snapshot_status = "PENDING"
oi_snapshot_status = "PRE-ENTRY FALLBACK; ENTRY REFRESH PENDING"

nifty_values = entry_snapshot[NIFTY_SYMBOL]
ce_values = entry_snapshot[ce_symbol]
pe_values = entry_snapshot[pe_symbol]
nifty_spot = ltp_from_quote(nifty_values, "NIFTY")
day_open = float(
    nifty_values.get("open_price", 0)
    or preselection_nifty_values.get("open_price", 0)
    or 0
)
if day_open <= 0:
    day_open = ""

ce_entry = ltp_from_quote(ce_values, "CE")
pe_entry = ltp_from_quote(pe_values, "PE")
ce_trade_time = market_timestamp(ce_values.get("tt"))
pe_trade_time = market_timestamp(pe_values.get("tt"))
quote_ages = [
    (capture_time - stamp).total_seconds()
    for stamp in (ce_trade_time, pe_trade_time)
    if stamp is not None
]
entry_data_status = (
    "FRESH" if len(quote_ages) == 2 and max(quote_ages) <= 10
    else "CHECK LTP AGE"
)
current_atm = nearest_atm(nifty_spot)
if current_atm != atm:
    entry_data_status = f"ATM SHIFT: selected {atm}, current spot maps to {current_atm}"
delay = (capture_time - target_dt).total_seconds()
if not TEST_MODE and delay > 5:
    entry_data_status += f"; LATE ENTRY +{delay:.1f}s"
entry_data_status += "; SPOT FROM PRE-ENTRY CONTRACT SNAPSHOT"

gap_text = (
    "Unavailable" if day_open == ""
    else "Gap Up" if day_open > previous_ohlc["close"]
    else "Gap Down" if day_open < previous_ohlc["close"]
    else "Flat"
)

ce_sl_values = [round(ce_entry * (1 + p / 100), 2) for p in SL_PERCENTAGES]
pe_sl_values = [round(pe_entry * (1 + p / 100), 2) for p in SL_PERCENTAGES]

print("\n=================================================")
print("NIFTY SHORT STRADDLE - PAPER FORWARD TEST")
print("=================================================")
print(f"Mode                   : {RUN_TYPE}")
print("Target entry           : 09:30 IST")
print(f"Entry snapshot received: {capture_time.strftime('%Y-%m-%d %H:%M:%S')} IST")
print(f"NIFTY                  : {nifty_spot:.2f}")
print(f"India VIX              : {india_vix if india_vix is not None else 'Unavailable'}")
print(f"ATM / expiry           : {atm} / {expiry['date']}")
print(f"CE                     : {ce_symbol} @ {ce_entry:.2f}")
print(f"PE                     : {pe_symbol} @ {pe_entry:.2f}")
print(f"CE last trade time     : {fmt_time(ce_trade_time)}")
print(f"PE last trade time     : {fmt_time(pe_trade_time)}")
print(f"Entry data status      : {entry_data_status}")
print(f"OI PCR / custom bias   : {pcr} / {market_bias}")
print("=================================================")

# ============================================================
# CREATE THE DAILY SUMMARY ROW AND THE SEVEN PARALLEL SCENARIOS
# ============================================================

state = {
    "ce_ltp": ce_entry,
    "pe_ltp": pe_entry,
    "ce_last_tick": capture_time,
    "pe_last_tick": capture_time,
    "ce_high": ce_entry,
    "ce_low": ce_entry,
    "pe_high": pe_entry,
    "pe_low": pe_entry,
    "complete": False,
    "final_ce_ltp": None,
    "final_pe_ltp": None,
    "scenarios": {},
}
for percent in SL_PERCENTAGES:
    state["scenarios"][percent] = {
        "ce_hit": False,
        "ce_hit_time": None,
        "ce_trigger_ltp": None,
        "ce_exit": None,
        "ce_exit_time": None,
        "ce_exit_reason": "",
        "pe_hit": False,
        "pe_hit_time": None,
        "pe_trigger_ltp": None,
        "pe_exit": None,
        "pe_exit_time": None,
        "pe_exit_reason": "",
    }

# Store trigger LTP values in the scenario state through the keys used above.
# This also keeps per-leg stop tracking independent for all seven percentages.
for scenario in state["scenarios"].values():
    scenario["ce_trigger_ltp"] = None
    scenario["pe_trigger_ltp"] = None


state_lock = threading.RLock()
pending_scenario_updates = set()
stop_event = threading.Event()
ws_holder = {"socket": None}
if not TEST_MODE:
    target_end = datetime.combine(capture_time.date(), EXIT_TIME, tzinfo=IST)
else:
    target_end = now_ist() + timedelta(minutes=MONITOR_MINUTES)

ws = data_ws.FyersDataSocket(
    access_token=f"{CLIENT_ID}:{ACCESS_TOKEN}",
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
threading.Thread(target=close_at_end, args=(target_end,), daemon=True).start()

print("\nConnecting to FYERS live feed...")

def connect_websocket():
    try:
        ws.connect()
    except Exception as exc:
        print("WebSocket connection warning:", exc, flush=True)


# Keep SDK connect/read-loop behavior off the main thread so a slow socket
# shutdown cannot prevent 15:00 finalization from running.
threading.Thread(
    target=connect_websocket,
    name="fyers-websocket-connect",
    daemon=True,
).start()

# The socket now processes ticks while metadata and Sheets work continues.
with state_lock:
    scenario_rows = [make_scenario_row(percent) for percent in SL_PERCENTAGES]
scenario_first_row = append_scenario_rows(scenario_rows)
scenario_row_numbers = {
    percent: scenario_first_row + index
    for index, percent in enumerate(SL_PERCENTAGES)
}
print(
    f"Google Sheet {SCENARIO_SHEET_NAME} rows: "
    f"{scenario_first_row}-{scenario_first_row + len(SL_PERCENTAGES) - 1}"
)


def poll_entry_metadata():
    global india_vix, vix_retrieved_at, vix_snapshot_status
    global call_oi, put_oi, pcr, market_bias, oi_retrieved_at, oi_snapshot_status
    results = collect_ready_requests(
        metadata_requests, expired=time_module.monotonic() >= metadata_deadline,
    )
    for name, (result, error) in results.items():
        try:
            if error is not None:
                raise error
            value, retrieved_at = result
            if name == "VIX":
                india_vix = ltp_from_quote(value[VIX_SYMBOL], "India VIX")
                vix_retrieved_at = retrieved_at
                vix_snapshot_status = "ENTRY REFRESH"
            else:
                if value.get("s") != "ok":
                    raise RuntimeError("OI refresh failed")
                data = value["data"]
                new_call = int(data["callOi"])
                new_put = int(data["putOi"])
                if new_call < 0 or new_put < 0:
                    raise ValueError("Negative OI")
                call_oi, put_oi = new_call, new_put
                pcr, market_bias = daily_bias(put_oi, call_oi)
                oi_retrieved_at = retrieved_at
                oi_snapshot_status = "ENTRY REFRESH"
            print(f"{name} snapshot retrieved at {fmt_time(retrieved_at)} IST", flush=True)
        except Exception as exc:
            if name == "VIX":
                vix_snapshot_status = "UNAVAILABLE"
            else:
                oi_snapshot_status = "PRE-ENTRY FALLBACK: entry refresh unavailable"
            print(f"{name} metadata unavailable: {type(exc).__name__}", flush=True)
    # Entry premiums, entry timestamp, stop thresholds and fills are never changed here.
    return bool(results)


poll_entry_metadata()
update_scenario_rows(SL_PERCENTAGES)
if daily_row_number is not None:
    write_daily_row("RUNNING")

while not stop_event.wait(timeout=0.5):
    changed_metadata = poll_entry_metadata()
    with state_lock:
        changes = set(pending_scenario_updates)
        pending_scenario_updates.clear()
    if changed_metadata:
        changes.update(SL_PERCENTAGES)
    if changes:
        try:
            update_scenario_rows(changes)
            if daily_row_number is not None:
                write_daily_row("RUNNING")
        except Exception as exc:
            with state_lock:
                pending_scenario_updates.update(changes)
            print(f"Sheet update retry queued: {type(exc).__name__}", flush=True)

# Pull one batched closing quote after the monitor has stopped; if the REST
# snapshot fails, use the final WebSocket LTP received before the deadline.
try:
    print("Requesting final CE/PE exit quote (8-second limit)...", flush=True)
    closing_snapshot = run_with_timeout(
        get_quotes,
        8,
        [ce_symbol, pe_symbol],
    )
    exit_snapshot_received_at = now_ist()
    final_ce_ltp = ltp_from_quote(closing_snapshot[ce_symbol], "final CE")
    final_pe_ltp = ltp_from_quote(closing_snapshot[pe_symbol], "final PE")
    final_ce_time = market_timestamp(closing_snapshot[ce_symbol].get("tt"))
    final_pe_time = market_timestamp(closing_snapshot[pe_symbol].get("tt"))
    print("Final CE/PE exit quote received.", flush=True)
except Exception as exc:
    print(
        f"Closing quote unavailable ({type(exc).__name__}); "
        "using last WebSocket prices.",
        flush=True,
    )
    exit_snapshot_received_at = now_ist()
    with state_lock:
        final_ce_ltp = state["ce_ltp"]
        final_pe_ltp = state["pe_ltp"]
        final_ce_time = state["ce_last_tick"]
        final_pe_time = state["pe_last_tick"]
    entry_data_status += "; EXIT FROM LAST LIVE TICKS"
    if any((target_end - stamp).total_seconds() > 10 for stamp in (final_ce_time, final_pe_time)):
        entry_data_status += "; CHECK EXIT TICK AGE"

state["final_ce_ltp"] = final_ce_ltp
state["final_pe_ltp"] = final_pe_ltp
final_reason = "TEST END" if TEST_MODE else "15:00 EXIT"
with state_lock:
    for percent in SL_PERCENTAGES:
        scenario = state["scenarios"][percent]
        if scenario["ce_exit"] is None:
            scenario["ce_exit"] = final_ce_ltp
            scenario["ce_exit_time"] = final_ce_time or exit_snapshot_received_at
            scenario["ce_exit_reason"] = final_reason
        if scenario["pe_exit"] is None:
            scenario["pe_exit"] = final_pe_ltp
            scenario["pe_exit_time"] = final_pe_time or exit_snapshot_received_at
            scenario["pe_exit_reason"] = final_reason
    state["complete"] = True

update_scenario_rows(SL_PERCENTAGES)
if daily_row_number is not None:
    write_daily_row("COMPLETED")

print("\n=================================================")
print("FINAL PAPER RESULTS BY STOP-LOSS SCENARIO")
print("=================================================")
for percent in SL_PERCENTAGES:
    scenario = state["scenarios"][percent]
    ce_net = round(ce_entry - scenario["ce_exit"], 2)
    pe_net = round(pe_entry - scenario["pe_exit"], 2)
    total_net = round(
        (ce_net + pe_net) * CONTRACT_QTY - ROUND_TRIP_CHARGES_RUPEES,
        2,
    )
    print(
        f"{percent:>2}% SL | "
        f"CE exit {scenario['ce_exit']:.2f} ({scenario['ce_exit_reason']}) "
        f"per-unit P&L {ce_net:.2f} | "
        f"PE exit {scenario['pe_exit']:.2f} ({scenario['pe_exit_reason']}) "
        f"per-unit P&L {pe_net:.2f} | "
        f"Net {total_net:.2f} after qty {CONTRACT_QTY} and charges "
        f"Rs {ROUND_TRIP_CHARGES_RUPEES}"
    )
print(f"Google Sheet tabs: {SCENARIO_SHEET_NAME}, {DAILY_SHEET_NAME}")
print("Paper monitoring only; no order was placed.")



