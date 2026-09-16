from fyers_apiv3 import fyersModel

# Your FYERS App ID
CLIENT_ID = "M2DACFCYUO-100"

# Read access token locally
with open("access_token.txt", "r") as f:
    ACCESS_TOKEN = f.read().strip()

# Create FYERS API client
fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID,
    token=ACCESS_TOKEN,
    is_async=False,
    log_path=""
)

# NIFTY 50 spot/index
data = {
    "symbols": "NSE:NIFTY50-INDEX"
}

response = fyers.quotes(data=data)

print("\nFYERS RESPONSE:")
print(response)