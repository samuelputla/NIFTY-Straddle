import os
from datetime import datetime
from fyers_apiv3 import fyersModel
from request_timing import run_with_timeout
client = fyersModel.FyersModel(client_id='M2DACFCYUO-100', token=os.environ['FYERS_ACCESS_TOKEN'].strip(), log_path='')
day = '2026-11-11'
target = int(datetime.fromisoformat(day + 'T09:30:00+05:30').timestamp())
try:
    response = run_with_timeout(lambda: client.history({'symbol':'NSE:INDIAVIX-INDEX','resolution':'1','date_format':'1','range_from':day,'range_to':day,'cont_flag':'0'}), 15)
    bars = [row for row in response.get('candles', []) if row[0] == target]
    print('VIX_0930_FYERS_BAR', bars if response.get('s') == 'ok' else 'UNAVAILABLE', 'CODE', response.get('code'))
except Exception as error:
    print('VIX_0930_UNAVAILABLE', type(error).__name__)
