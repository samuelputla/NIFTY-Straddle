"""Copy the two research tabs to the private Straddle Lab Site."""
import json
import os
import sys
import time

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

SHEET_ID = "1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI"
DAILY_SHEET = "Nifty Daily straddle"
WEEKLY_SHEET = "Nifty Weekly Strangle"
DESTINATION = "https://nifty-straddle-lab.cosmicbay1.chatgpt.site/api/sync"
SOURCE = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID + "/values/"


def read_values(session, a1_range):
    response = session.get(SOURCE + a1_range, params={"valueRenderOption": "FORMATTED_VALUE"}, timeout=45)
    return response


def weekly_snapshot(session):
    # Count populated cycle rows first, then sync only the newest 4,000 records.
    # This keeps the Site request below its payload ceiling over long histories.
    count = read_values(session, f"'{WEEKLY_SHEET}'!A:A")
    if count.status_code != 200:
        return None
    last_row = len(count.json().get("values", []))
    if not last_row:
        return None
    header_response = read_values(session, f"'{WEEKLY_SHEET}'!A1:AD1")
    if header_response.status_code != 200:
        raise RuntimeError(f"Weekly sheet header read failed: HTTP {header_response.status_code}")
    header = header_response.json().get("values", [[]])[0]
    if last_row == 1:
        return [header]
    first_row = max(2, last_row - 3999)
    body = read_values(session, f"'{WEEKLY_SHEET}'!A{first_row}:AD{last_row}")
    if body.status_code != 200:
        raise RuntimeError(f"Weekly sheet rows read failed: HTTP {body.status_code}")
    return [header] + body.json().get("values", [])


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

        try:
            weekly_values = weekly_snapshot(session)
        except RuntimeError as exc:
            print(f"{exc}; daily dashboard data remains synced.")
            return
        if not weekly_values:
            print(f"{WEEKLY_SHEET} is not available yet; daily dashboard data remains synced.")
            return
        send(WEEKLY_SHEET, weekly_values, token)
    except Exception as exc:
        sys.exit(f"Sync failed ({type(exc).__name__}); no credentials or sheet data logged.")


if __name__ == "__main__":
    main()

