from fyers_apiv3 import fyersModel
from datetime import datetime, time
import time as time_module
from zoneinfo import ZoneInfo

# ============================================================
# FYERS CONFIGURATION
# ============================================================

CLIENT_ID = "M2DACFCYUO-100"

with open("access_token.txt", "r") as f:
    ACCESS_TOKEN = f.read().strip()

fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path=""
)

IST = ZoneInfo("Asia/Kolkata")

# ============================================================
# STRATEGY SETTINGS
# ============================================================

TARGET_TIME = time(9, 30, 0)

NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
VIX_SYMBOL = "NSE:INDIAVIX-INDEX"

SL_PERCENTAGES = [10, 15, 20, 25, 30, 35, 40]

# ============================================================
# HEADER
# ============================================================

print("\n==============================================")
print("NIFTY SHORT STRADDLE - ENTRY TEST")
print("==============================================")
print("Target Entry : 09:30 IST")
print("India VIX    : YES")
print("Mode         : PAPER / FORWARD TEST")
print("==============================================")

# ============================================================
# WAIT UNTIL 09:30 IST
# ============================================================

print("\nWaiting for 09:30 IST...")

while datetime.now(IST).time() < TARGET_TIME:

    now = datetime.now(IST)

    target = datetime.combine(
        now.date(),
        TARGET_TIME,
        tzinfo=IST
    )

    remaining = int((target - now).total_seconds())

    if remaining > 0:
        print(
            f"\rStarting in {remaining} seconds...",
            end=""
        )

    time_module.sleep(1)

print("\n")

# ============================================================
# ACTUAL CAPTURE TIMESTAMP
# ============================================================

capture_time = datetime.now(IST)

print("==============================================")
print("09:30 ENTRY CAPTURE")
print("==============================================")
print(
    "Capture Time : "
    + capture_time.strftime("%Y-%m-%d %H:%M:%S")
    + " IST"
)

# ============================================================
# GET NIFTY SPOT
# ============================================================

quote_data = {
    "symbols": NIFTY_SYMBOL
}

quote_response = fyers.quotes(data=quote_data)

if quote_response.get("s") != "ok":

    print("\n❌ NIFTY quote failed")
    print(quote_response)
    raise SystemExit

nifty_spot = float(
    quote_response["d"][0]["v"]["lp"]
)

# ============================================================
# GET INDIA VIX
# ============================================================

vix_data = {
    "symbols": VIX_SYMBOL
}

vix_response = fyers.quotes(data=vix_data)

if vix_response.get("s") != "ok":

    print("\n❌ India VIX quote failed")
    print(vix_response)

    print(
        "\nThe NIFTY entry can still be captured, "
        "but today's test requires India VIX."
    )

    raise SystemExit

india_vix = float(
    vix_response["d"][0]["v"]["lp"]
)

# ============================================================
# DETERMINE ATM
# ============================================================

atm = int((nifty_spot + 25) // 50) * 50

# ============================================================
# GET OPTION CHAIN
# ============================================================

optionchain_data = {
    "symbol": NIFTY_SYMBOL,
    "strikecount": 5,
    "timestamp": ""
}

optionchain_response = fyers.optionchain(
    data=optionchain_data
)

if optionchain_response.get("s") != "ok":

    print("\n❌ Option chain failed")
    print(optionchain_response)
    raise SystemExit

chain = optionchain_response["data"]

# ============================================================
# GET NEAREST EXPIRY
# ============================================================

expiry_data = chain.get("expiryData", [])

if not expiry_data:

    print("\n❌ No expiry data received")
    raise SystemExit

expiry = expiry_data[0]

# ============================================================
# FIND ATM CE + PE
# ============================================================

ce = None
pe = None

for option in chain["optionsChain"]:

    if option.get("strike_price") == atm:

        if option.get("option_type") == "CE":
            ce = option

        elif option.get("option_type") == "PE":
            pe = option

# ============================================================
# VALIDATE CONTRACTS
# ============================================================

if ce is None:

    print("\n❌ ATM CE not found")
    raise SystemExit

if pe is None:

    print("\n❌ ATM PE not found")
    raise SystemExit

# ============================================================
# ENTRY PRICES
# ============================================================

ce_entry = float(ce["ltp"])
pe_entry = float(pe["ltp"])

# ============================================================
# DISPLAY ENTRY DATA
# ============================================================

print("\nNIFTY DATA")
print("----------------------------------------------")
print(f"NIFTY Spot  : {nifty_spot:.2f}")
print(f"India VIX   : {india_vix:.2f}")
print(f"ATM Strike  : {atm}")
print(f"Expiry      : {expiry['date']}")

print("\nCALL LEG")
print("----------------------------------------------")
print(f"Symbol      : {ce['symbol']}")
print(f"LTP         : {ce['ltp']}")
print(f"Bid         : {ce.get('bid')}")
print(f"Ask         : {ce.get('ask')}")

print("\nPUT LEG")
print("----------------------------------------------")
print(f"Symbol      : {pe['symbol']}")
print(f"LTP         : {pe['ltp']}")
print(f"Bid         : {pe.get('bid')}")
print(f"Ask         : {pe.get('ask')}")

# ============================================================
# CALCULATE SL LEVELS
# ============================================================

print("\n==============================================")
print("STOP LOSS LEVELS")
print("==============================================")

print(
    f"{'SL %':<8}"
    f"{'CE Entry':<12}"
    f"{'CE SL':<12}"
    f"{'PE Entry':<12}"
    f"{'PE SL':<12}"
)

print("----------------------------------------------")

for percentage in SL_PERCENTAGES:

    ce_sl = ce_entry * (1 + percentage / 100)
    pe_sl = pe_entry * (1 + percentage / 100)

    print(
        f"{percentage:<8}"
        f"{ce_entry:<12.2f}"
        f"{ce_sl:<12.2f}"
        f"{pe_entry:<12.2f}"
        f"{pe_sl:<12.2f}"
    )

# ============================================================
# FINAL ENTRY SUMMARY
# ============================================================

print("\n==============================================")
print("ENTRY RECORD")
print("==============================================")

print(
    f"Date         : {capture_time.strftime('%Y-%m-%d')}"
)

print(
    f"Time         : {capture_time.strftime('%H:%M:%S')} IST"
)

print(
    f"NIFTY Spot   : {nifty_spot:.2f}"
)

print(
    f"India VIX    : {india_vix:.2f}"
)

print(
    f"ATM          : {atm}"
)

print(
    f"Expiry       : {expiry['date']}"
)

print(
    f"CE Entry     : {ce_entry:.2f}"
)

print(
    f"PE Entry     : {pe_entry:.2f}"
)

print(
    f"CE Symbol    : {ce['symbol']}"
)

print(
    f"PE Symbol    : {pe['symbol']}"
)

print("==============================================")
print("✅ ENTRY CAPTURE COMPLETE")
print("==============================================")