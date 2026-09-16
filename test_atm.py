from fyers_apiv3 import fyersModel

CLIENT_ID = "M2DACFCYUO-100"

with open("access_token.txt", "r") as f:
    ACCESS_TOKEN = f.read().strip()

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

# Nearest 50-point strike
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

print("\n==============================")
print("NIFTY STRADDLE SETUP")
print("==============================")

print(f"NIFTY Spot : {spot}")
print(f"ATM Strike : {atm}")
print(f"Expiry     : {expiry['date']}")

print("\nCALL")
print(f"Symbol : {ce['symbol']}")
print(f"LTP    : {ce['ltp']}")
print(f"Bid    : {ce['bid']}")
print(f"Ask    : {ce['ask']}")

print("\nPUT")
print(f"Symbol : {pe['symbol']}")
print(f"LTP    : {pe['ltp']}")
print(f"Bid    : {pe['bid']}")
print(f"Ask    : {pe['ask']}")

print("==============================")