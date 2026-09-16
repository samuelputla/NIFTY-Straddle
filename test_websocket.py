from fyers_apiv3.FyersWebsocket import data_ws
import time

CLIENT_ID = "M2DACFCYUO-100"

with open("access_token.txt", "r") as f:
    ACCESS_TOKEN = f.read().strip()

# FYERS WebSocket requires: APP_ID:ACCESS_TOKEN
TOKEN = CLIENT_ID + ":" + ACCESS_TOKEN

symbols = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTY2691523400CE",
    "NSE:NIFTY2691523400PE"
]

def onmessage(message):
    print(message)

def onerror(message):
    print("ERROR:", message)

def onclose(message):
    print("CLOSED:", message)

def onopen():
    print("WebSocket connected!")
    fyers.subscribe(
        symbols=symbols,
        data_type="SymbolUpdate"
    )
    fyers.keep_running()

fyers = data_ws.FyersDataSocket(
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

print("Connecting to FYERS WebSocket...")
fyers.connect()

while True:
    time.sleep(1)