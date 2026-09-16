from fyers_apiv3 import fyersModel
import webbrowser
import getpass

CLIENT_ID = "M2DACFCYUO-100"
REDIRECT_URI = "https://fyers.in"

SECRET_KEY = getpass.getpass("Enter FYERS Secret ID: ")

session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_KEY,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code"
)

# Generate FYERS login URL
login_url = session.generate_authcode()

print("\n==============================================")
print("FYERS LOGIN")
print("==============================================")
print("\nOpening FYERS login page...")
print("\nIf it does not open automatically, copy this URL:")
print(login_url)
print("==============================================\n")

webbrowser.open(login_url)

print("After logging in, FYERS will redirect you.")
print("Copy the auth_code from the redirected URL.")
print()

AUTH_CODE = input("Paste auth_code: ").strip()

session.set_token(AUTH_CODE)

response = session.generate_token()

print("\nFYERS RESPONSE:")
print(response)

if response.get("s") == "ok":

    access_token = response["access_token"]

    with open("access_token.txt", "w") as f:
        f.write(access_token)

    print("\nSUCCESS!")
    print("Access token saved locally to access_token.txt")

else:

    print("\nToken generation failed.")
    print("Code:", response.get("code"))
    print("Message:", response.get("message"))