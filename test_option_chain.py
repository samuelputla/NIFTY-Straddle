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

print("\nFYERS OPTION CHAIN RESPONSE:")
print(response)