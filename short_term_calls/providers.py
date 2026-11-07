"""Only public NSE downloads and authenticated FYERS history GETs are exposed."""
import csv
import io
import json
import os
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .engine import IST, candles, digest


class DataUnavailable(RuntimeError): pass


class History:
    def __init__(self, output, *, simulation_url=None):
        import requests
        self.http=requests.Session()
        self.output=Path(output);self.output.mkdir(parents=True,exist_ok=True)
        self.previous=0
        if simulation_url:
            parsed=urlparse(simulation_url)
            if parsed.hostname not in ('127.0.0.1','localhost') or parsed.scheme!='http':
                raise ValueError('Simulation must be loopback HTTP')
            self.url=simulation_url.rstrip('/')+'/history'
            self.http.headers['Authorization']='SIMULATION-NOT-A-CREDENTIAL'
        else:
            token=os.environ.get('FYERS_ACCESS_TOKEN','').strip()
            if not token: raise DataUnavailable('FYERS credential unavailable')
            self.url='https://api-t1.fyers.in/data/history'
            self.http.headers['Authorization']=os.getenv('FYERS_CLIENT_ID','M2DACFCYUO-100')+':'+token

    def fetch(self,symbol,start,end):
        delay=2.1-(time.monotonic()-self.previous)
        if delay>0:time.sleep(delay)
        self.previous=time.monotonic()
        params={'symbol':symbol,'resolution':'1','date_format':'0',
                'range_from':str(int(start.timestamp())),
                'range_to':str(int((end.replace(second=0,microsecond=0)-timedelta(minutes=1)).timestamp())),
                'cont_flag':'1'}
        try:r=self.http.get(self.url,params=params,timeout=(5,25))
        except Exception:raise DataUnavailable('FYERS transport unavailable') from None
        if r.status_code in (401,403):raise DataUnavailable('FYERS authentication unavailable')
        if r.status_code==429:raise DataUnavailable('FYERS rate limit; stopped without retry')
        if r.status_code!=200:raise DataUnavailable('FYERS HTTP '+str(r.status_code))
        try:body=r.json()
        except Exception:raise DataUnavailable('FYERS non-JSON response') from None
        if not isinstance(body,dict):raise DataUnavailable('FYERS malformed response')
        if body.get('code') in (-429,429,-360,'429','-429','-360'):
            raise DataUnavailable('FYERS rate limit; stopped without retry')
        if body.get('s')!='ok' or not isinstance(body.get('candles'),list):
            raise DataUnavailable('FYERS data unavailable')
        raw=body['candles']
        try:
            clean=candles(raw,end)
            if any(r[0]<int(start.timestamp()) or r[0]>int(end.timestamp()) for r in raw):
                raise ValueError('Out-of-range candle')
        except Exception:raise DataUnavailable('FYERS invalid candle evidence') from None
        safe=symbol.replace(':','_').replace('/','_')
        (self.output/(safe+'-'+digest(params)[:10]+'.json')).write_text(
            json.dumps({'source':'FYERS','params':params,'fetched_at':datetime.now(IST).isoformat(),
                        'candles':raw,'sha256':digest(raw)}),encoding='utf-8')
        return clean


def bhavcopy(day,output):
    import requests
    name=f'BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv'
    url='https://nsearchives.nseindia.com/content/cm/'+name+'.zip'
    try:
        r=requests.get(url,timeout=(5,25),headers={'User-Agent':'ShortTermPaperResearch/1.0'})
        if r.status_code!=200:raise ValueError('Unavailable archive')
        archive=zipfile.ZipFile(io.BytesIO(r.content))
        data=archive.read(name)
        rows=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
        if not rows or any(row['TradDt']!=day.isoformat() for row in rows):raise ValueError('Wrong session')
        (Path(output)/name).write_bytes(data)
        return {r['TckrSymb']:r for r in rows if r['SctySrs']=='EQ'}
    except Exception:raise DataUnavailable('NSE daily archive unavailable: '+day.isoformat()) from None
