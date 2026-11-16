"""FYERS paper basket estimates for the option observation worker."""
import math
import os
import time

import requests

TAB = 'Option Basket Margins'
HEADERS = ['Event ID', 'Date', 'Family', 'Expiry Choice', 'Expiry', 'SL %', 'Cycle',
           'Entry Time', 'CE Symbol', 'PE Symbol', 'Quantity Per Leg', 'Product',
           'Estimated At', 'Basket Margin INR', 'Status']
URL = 'https://api-t1.fyers.in/api/v3/multiorder/margin'


def estimate_margin(symbols, quantity):
    token = os.environ.get('FYERS_ACCESS_TOKEN', '').strip()
    if not token:
        return '', 'FYERS token unavailable'
    app_id = os.environ.get('FYERS_CLIENT_ID', '').strip() or 'M2DACFCYUO-100'
    authorization = token if token.startswith(app_id + ':') else f'{app_id}:{token}'
    basket = [dict(symbol=symbol, qty=quantity, side=-1, type=2, productType='INTRADAY',
                   limitPrice=0, stopPrice=0, stopLoss=0, takeProfit=0) for symbol in symbols]
    try:
        for attempt in range(2):
            try:
                response = requests.post(URL, headers={'Authorization': authorization},
                                         json={'data': basket}, timeout=(3, 6))
                response.raise_for_status()
                break
            except (requests.Timeout, requests.ConnectionError):
                if attempt:
                    raise
            except requests.HTTPError as error:
                if attempt or error.response.status_code not in (429, 500, 502, 503, 504):
                    raise
            time.sleep(2)
        result = response.json()
        margin = result.get('data', {}).get('margin_total')
        if (result.get('s') == 'ok' and type(margin) in (int, float)
                and math.isfinite(margin) and margin > 0):
            return margin, 'FYERS estimate'
        return '', 'FYERS margin unavailable'
    except (requests.RequestException, ValueError, AttributeError):
        return '', 'FYERS margin request failed'
