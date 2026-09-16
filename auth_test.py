from fyers_apiv3 import fyersModel
import webbrowser

CLIENT_ID = "M2DACFCYUO-100"
REDIRECT_URI = "https://fyers.in"

session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code"
)

login_url = session.generate_authcode()

print("\nOpening FYERS login...")
print("\nLogin URL:")
print(login_url)

webbrowser.open(login_url)