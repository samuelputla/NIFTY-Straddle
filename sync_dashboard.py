"""Copy the daily straddle tab to the private Straddle Lab Site."""
import json
import os
import sys
import time

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

SHEET_ID = "1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI"
DAILY_SHEET = "Nifty Daily straddle"
DESTINATION = "https://nifty-straddle-lab.cosmicbay1.chatgpt.site/api/sync"
SOURCE = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID + "/values/"


def read_values(session, a1_range):
    response = session.get(SOURCE + a1_range, params={"valueRenderOption": "FORMATTED_VALUE"}, timeout=45)
    return response


def send(tab, values, token):
    payload = {"spreadsheetId": SHEET_ID, "sheet": tab, "values": values}
    headers = {"OAI-Sites-Authorization": f"Bearer {token}"}
    for attempt in range(3):
        result = requests.post(DESTINATION, json=payload, headers=headers, timeout=45, allow_redirects=False)
        if result.status_code == 200 and result.json().get("ok") is True:
            print(f"Dashboard synced {tab}: {len(values)-1} rows.")
            return
        if result.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
            raise RuntimeError(f"Dashboard sync failed for {tab}: HTTP {result.status_code}")
        time.sleep(5 * (attempt + 1))


def main():
    token = os.environ.get("STRADDLE_DASHBOARD_TOKEN", "").strip()
    service_account = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not token:
        sys.exit("Missing STRADDLE_DASHBOARD_TOKEN repository secret.")
    if not service_account:
        sys.exit("Missing GOOGLE_SERVICE_ACCOUNT_JSON repository secret.")
    try:
        credentials = Credentials.from_service_account_info(
            json.loads(service_account), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        session = AuthorizedSession(credentials)
        daily = read_values(session, f"'{DAILY_SHEET}'!A1:CV10000")
        if daily.status_code != 200:
            raise RuntimeError(f"Google Sheets read failed for {DAILY_SHEET}: HTTP {daily.status_code}")
        daily_values = daily.json().get("values", [])
        if not daily_values:
            raise RuntimeError(f"{DAILY_SHEET} returned no headers; previous dashboard data remains saved.")
        send(DAILY_SHEET, daily_values, token)
        v2 = read_values(session, "'Straddle V2 Strategy'!A1:AZ1000")
        if v2.status_code != 200:
            raise RuntimeError(f"Google Sheets read failed for V2: HTTP {v2.status_code}")
        v2_values = v2.json().get("values", [])
        if not v2_values:
            raise RuntimeError("V2 sheet returned no headers")
        send("Straddle V2 Strategy", v2_values, token)
        next_expiry = read_values(session, "'Next Expiry Straddle'!A1:BN1000")
        if next_expiry.status_code != 200:
            raise RuntimeError("Google Sheets read failed for next-expiry study")
        next_values = next_expiry.json().get("values", [])
        if not next_values:
            raise RuntimeError("Next-expiry sheet returned no headers")
        send("Next Expiry Straddle", next_values, token)
        next_expiry = read_values(session, "'Next Expiry Straddle'!A1:BN1000")
        if next_expiry.status_code != 200:
            raise RuntimeError("Google Sheets read failed for next-expiry study")
        next_values = next_expiry.json().get("values", [])
        if not next_values:
            raise RuntimeError("Next-expiry sheet returned no headers")
        send("Next Expiry Straddle", next_values, token)

    except Exception as exc:
        sys.exit(f"Sync failed ({type(exc).__name__}); no credentials or sheet data logged.")


if __name__ == "__main__":
    main()

