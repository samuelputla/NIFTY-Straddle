from fyers_apiv3.FyersWebsocket import data_ws
from datetime import datetime, time
from zoneinfo import ZoneInfo
import time as time_module

CLIENT_ID = "M2DACFCYUO-100"

with open("access_token.txt", "r") as f:
    ACCESS_TOKEN = f.read().strip()

IST = ZoneInfo("Asia/Kolkata")

# ============================================================
# TODAY'S ENTRY — 09:36
# ============================================================

ENTRY_TIME = "09:36"

CE_SYMBOL = "NSE:NIFTY2691523450CE"
PE_SYMBOL = "NSE:NIFTY2691523450PE"

CE_ENTRY = 61.20
PE_ENTRY = 53.85

SL_PERCENTAGES = [10, 15, 20, 25, 30, 35, 40]

# ============================================================
# CREATE 7 INDEPENDENT STRATEGIES
# ============================================================

strategies = {}

for pct in SL_PERCENTAGES:
    strategies[pct] = {
        "ce_sl": CE_ENTRY * (1 + pct / 100),
        "pe_sl": PE_ENTRY * (1 + pct / 100),

        "ce_open": True,
        "pe_open": True,

        "ce_exit": None,
        "pe_exit": None,

        "ce_exit_reason": None,
        "pe_exit_reason": None,

        "ce_exit_time": None,
        "pe_exit_time": None,
    }

# Last valid tick at or before 15:00
last_valid_price = {
    CE_SYMBOL: None,
    PE_SYMBOL: None
}

last_valid_time = {
    CE_SYMBOL: None,
    PE_SYMBOL: None
}

# ============================================================
# DISPLAY SETUP
# ============================================================

print("\n==============================================")
print("NIFTY SHORT STRADDLE - LIVE FORWARD TEST")
print("==============================================")

print(f"Entry time : {ENTRY_TIME} IST")
print(f"CE         : {CE_SYMBOL}")
print(f"CE Entry   : {CE_ENTRY:.2f}")
print(f"PE         : {PE_SYMBOL}")
print(f"PE Entry   : {PE_ENTRY:.2f}")

print("\nSL LEVELS")
print("----------------------------------------------")

for pct in SL_PERCENTAGES:
    s = strategies[pct]

    print(
        f"{pct:>2}%   "
        f"CE SL: {s['ce_sl']:.2f}   "
        f"PE SL: {s['pe_sl']:.2f}"
    )

print("----------------------------------------------")
print("Monitoring starts NOW.")
print("15:00 will close any remaining legs.")
print("==============================================\n")


# ============================================================
# LIVE MESSAGE HANDLER
# ============================================================

def onmessage(message):

    symbol = message.get("symbol")
    ltp = message.get("ltp")
    feed_time = message.get("exch_feed_time")

    if symbol not in last_valid_price:
        return

    if ltp is None:
        return

    ltp = float(ltp)

    # Convert exchange timestamp to IST
    if feed_time:
        tick_dt = datetime.fromtimestamp(
            float(feed_time),
            tz=IST
        )
    else:
        tick_dt = datetime.now(IST)

    # --------------------------------------------------------
    # Keep only ticks at or before 15:00
    # --------------------------------------------------------

    if tick_dt.time() <= time(15, 0, 0):

        last_valid_price[symbol] = ltp
        last_valid_time[symbol] = tick_dt

    # --------------------------------------------------------
    # SL detection
    # --------------------------------------------------------

    for pct in SL_PERCENTAGES:

        strategy = strategies[pct]

        # ============================
        # CE SL
        # ============================

        if (
            symbol == CE_SYMBOL
            and strategy["ce_open"]
            and ltp >= strategy["ce_sl"]
        ):

            strategy["ce_open"] = False
            strategy["ce_exit"] = ltp
            strategy["ce_exit_reason"] = "SL"
            strategy["ce_exit_time"] = tick_dt

            print(
                f"\n🔴 {pct}% STRATEGY — CE SL HIT"
            )

            print(
                f"   Time       : {tick_dt.strftime('%H:%M:%S')}"
            )

            print(
                f"   SL Level   : {strategy['ce_sl']:.2f}"
            )

            print(
                f"   Exit Price : {ltp:.2f}"
            )

        # ============================
        # PE SL
        # ============================

        if (
            symbol == PE_SYMBOL
            and strategy["pe_open"]
            and ltp >= strategy["pe_sl"]
        ):

            strategy["pe_open"] = False
            strategy["pe_exit"] = ltp
            strategy["pe_exit_reason"] = "SL"
            strategy["pe_exit_time"] = tick_dt

            print(
                f"\n🔴 {pct}% STRATEGY — PE SL HIT"
            )

            print(
                f"   Time       : {tick_dt.strftime('%H:%M:%S')}"
            )

            print(
                f"   SL Level   : {strategy['pe_sl']:.2f}"
            )

            print(
                f"   Exit Price : {ltp:.2f}"
            )


def onerror(message):
    print("\n❌ WebSocket ERROR:")
    print(message)


def onclose(message):
    print("\n⚠️ WebSocket CLOSED:")
    print(message)


def onopen():

    print("✅ WebSocket connected!")

    fyers_ws.subscribe(
        symbols=[
            CE_SYMBOL,
            PE_SYMBOL
        ],
        data_type="SymbolUpdate"
    )

    print("✅ CE + PE subscribed.")
    print("")


# ============================================================
# WEBSOCKET CONNECTION
# ============================================================

TOKEN = CLIENT_ID + ":" + ACCESS_TOKEN

fyers_ws = data_ws.FyersDataSocket(
    access_token=TOKEN,
    log_path="",
    litemode=False,
    write_to_file=False,
    reconnect=True,
    on_connect=onopen,
    on_close=onclose,
    on_error=onerror,
    on_message=onmessage
)

fyers_ws.connect()


# ============================================================
# WAIT UNTIL 15:00
# ============================================================

try:

    while True:

        now = datetime.now(IST)

        if now.time() >= time(15, 0, 0):
            break

        time_module.sleep(1)


except KeyboardInterrupt:

    print("\n⚠️ PROGRAM MANUALLY STOPPED.")
    raise SystemExit


# ============================================================
# 15:00 EXIT
# ============================================================

print("\n==============================================")
print("15:00 REACHED")
print("CLOSING REMAINING POSITIONS")
print("==============================================")

for pct in SL_PERCENTAGES:

    strategy = strategies[pct]

    # CE remaining
    if strategy["ce_open"]:

        exit_price = last_valid_price[CE_SYMBOL]

        if exit_price is not None:

            strategy["ce_open"] = False
            strategy["ce_exit"] = exit_price
            strategy["ce_exit_reason"] = "15:00"
            strategy["ce_exit_time"] = last_valid_time[CE_SYMBOL]

    # PE remaining
    if strategy["pe_open"]:

        exit_price = last_valid_price[PE_SYMBOL]

        if exit_price is not None:

            strategy["pe_open"] = False
            strategy["pe_exit"] = exit_price
            strategy["pe_exit_reason"] = "15:00"
            strategy["pe_exit_time"] = last_valid_time[PE_SYMBOL]


# ============================================================
# FINAL RESULTS
# ============================================================

print("\n==============================================")
print("FINAL FORWARD-TEST RESULTS")
print("==============================================")

for pct in SL_PERCENTAGES:

    strategy = strategies[pct]

    ce_exit = strategy["ce_exit"]
    pe_exit = strategy["pe_exit"]

    ce_pnl = CE_ENTRY - ce_exit if ce_exit is not None else 0
    pe_pnl = PE_ENTRY - pe_exit if pe_exit is not None else 0

    total_pnl = ce_pnl + pe_pnl

    print(f"\n----- {pct}% SL -----")

    print(
        f"CE: Entry {CE_ENTRY:.2f} → "
        f"Exit {ce_exit:.2f} "
        f"({strategy['ce_exit_reason']}) "
        f"= {ce_pnl:+.2f} points"
    )

    print(
        f"PE: Entry {PE_ENTRY:.2f} → "
        f"Exit {pe_exit:.2f} "
        f"({strategy['pe_exit_reason']}) "
        f"= {pe_pnl:+.2f} points"
    )

    print(
        f"TOTAL P/L = {total_pnl:+.2f} points"
    )

print("\n==============================================")
print("✅ TEST COMPLETE")
print("==============================================")