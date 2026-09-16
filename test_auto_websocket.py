from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
import time

CLIENT_ID = "M2DACFCYUO-100"

with open("access_token.txt", "r") as f:
    ACCESS_TOKEN = f.read().strip()

# -----------------------------
# STEP 1: GET OPTION CHAIN
# -----------------------------

fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path=""
)

data = {
    "symbol": "NSE:NIFTY50-INDEX",
    "strikecount": 5,
    "timestamp": ""
}

response = fyers.optionchain(data=data)

if response.get("s") != "ok":
    print("Option chain failed:")
    print(response)
    raise SystemExit

chain = response["data"]

# NIFTY spot
spot = chain["optionsChain"][0]["ltp"]

# Nearest 50-point ATM
atm = round(spot / 50) * 50

# Nearest expiry
expiry = chain["expiryData"][0]

ce = None
pe = None

for option in chain["optionsChain"]:
    if option.get("strike_price") == atm:
        if option.get("option_type") == "CE":
            ce = option
        elif option.get("option_type") == "PE":
            pe = option

if ce is None or pe is None:
    print("ATM CE/PE not found")
    raise SystemExit

CE_SYMBOL = ce["symbol"]
PE_SYMBOL = pe["symbol"]

print("\n==============================")
print("AUTOMATIC STRADDLE SELECTION")
print("==============================")
print(f"NIFTY Spot : {spot}")
print(f"ATM Strike : {atm}")
print(f"Expiry     : {expiry['date']}")
print(f"CE         : {CE_SYMBOL}")
print(f"PE         : {PE_SYMBOL}")

# -----------------------------
# STEP 2: CONNECT WEBSOCKET
# -----------------------------

TOKEN = CLIENT_ID + ":" + ACCESS_TOKEN

symbols = [
    "NSE:NIFTY50-INDEX",
    CE_SYMBOL,
    PE_SYMBOL
]

def onmessage(message):
    symbol = message.get("symbol", "")
    ltp = message.get("ltp", "")
    
    if symbol and ltp:
        print(f"{symbol}  LTP: {ltp}")

def onerror(message):
    print("ERROR:", message)

def onclose(message):
    print("CLOSED:", message)

def onopen():
    print("\nWebSocket connected!")
    print("Waiting for live prices...\n")

    fyers_ws.subscribe(
        symbols=symbols,
        data_type="SymbolUpdate"
    )

    fyers_ws.keep_running()

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

print("\nConnecting to WebSocket...")
fyers_ws.connect()

while True:
    time.sleep(1)