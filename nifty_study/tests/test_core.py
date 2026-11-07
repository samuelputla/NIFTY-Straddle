import json
import math
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta
from nifty_study.calendar import session,next_session
from nifty_study.core import IST,daily_features,intraday_features,screen,review_outcome
from nifty_study.run import evaluate,news_evidence,eligible_evidence
from nifty_study.adapters import universe,Sheets

def bars(n=120):
    start=datetime(2026,3,1,tzinfo=IST)
    return [[int((start+timedelta(days=i)).timestamp()),100+i,102+i,99+i,101+i,1000+i] for i in range(n)]

class CoreTests(unittest.TestCase):
    def test_calendar_special_and_holiday(self):
        self.assertEqual(next_session('2026-11-06'),'2026-11-08')
        self.assertEqual(session('2026-11-08')['open'],'14:20')
        self.assertEqual(next_session('2026-11-09'),'2026-11-11')
        with self.assertRaises(ValueError): session('2027-01-01')

    def test_gap_reconciliation_and_prior_resistance(self):
        b=bars();f=daily_features(b,b)
        self.assertAlmostEqual((1+f['gap']/100)*(1+f['intraday']/100)-1,f['return']/100)
        self.assertEqual(f['resistance'],max(x[2] for x in b[-21:-1]))
        self.assertEqual(f['rs20'],0)
        self.assertEqual(f['rsi14'],100)
        self.assertTrue(all(math.isfinite(f[x]) for x in ['adx14','atr14','rvol20','macd']))

    def test_bad_volume_and_duplicate_rejected(self):
        b=bars();b[-1][5]=0
        with self.assertRaises(ValueError): daily_features(b,b)
        b=bars();b.append(b[-1])
        with self.assertRaises(ValueError): daily_features(b,b)

    def test_equal_scores_deterministic(self):
        rows=[dict(symbol=x,rs20=1,momentum20=1,rvol20=1,structure=1,sector20=1) for x in ['Z','A']]
        self.assertEqual([r['symbol'] for r in screen(rows)],['A','Z'])
        self.assertEqual(rows[0]['score'],.5)
        rows[0]['rs20']=float('nan')
        with self.assertRaises(ValueError): screen(rows)

    def test_intraday_approximation(self):
        f=intraday_features(bars(4))
        self.assertTrue(99<=f['poc']<=105)
        self.assertGreater(f['vwap'],0)

    def test_universe_not_40(self):
        with self.assertRaises(Exception): universe('Symbol,Industry,Series\nINFY,IT,EQ\n')

    def test_evidence_cutoff(self):
        now=datetime.fromisoformat('2026-11-09T18:30:00+05:30')
        r={'Symbol':'INFY','Verified':'TRUE','Published At':'2026-11-09T18:00:00+05:30',
           'Observed At':'2026-11-09T18:10:00+05:30','Source URL':'https://www.nseindia.com/example'}
        self.assertEqual(len(eligible_evidence([r],now,'INFY')),1)
        r['Published At']='2026-11-10T18:00:00+05:30'
        self.assertEqual(eligible_evidence([r],now,'INFY'),[])

    def test_complete_forecast_review_and_late_rejection(self):
        actual=[dict(symbol=f'S{i:02}',**{'return':50-i,'gap':1,'intraday':2}) for i in range(50)]
        prior=[{'Forecast ID':'f','Target Session':'2026-11-09','Symbol':r['symbol'],'Selected':str(i<5),
                'Created At':'2026-11-08T18:30:00+05:30','Rule Version':'v1',
                'Baseline Prior Winner Rank':str(i+1),'Baseline Momentum Rank':str(i+1),'Baseline Sector Rank':str(i+1)} for i,r in enumerate(actual)]
        reviews,changes,summary=evaluate(prior,actual,'2026-11-09','key')
        self.assertEqual(len(reviews),50);self.assertEqual(len(changes),0)
        self.assertEqual(summary[0]['precision_at_5'],1)
        prior[0]['Created At']='2026-11-09T10:00:00+05:30'
        self.assertEqual(evaluate(prior,actual,'2026-11-09','key')[0],[])
        self.assertEqual(review_outcome(True,6),'FALSE POSITIVE')
        self.assertEqual(review_outcome(False,1),'MISSED LEADER')

    def test_schema_publication_and_formula_safety(self):
        # Verify atomic payload construction and retry guard independently of Google auth.
        s=Sheets.__new__(Sheets);s.schema={'Study Runs':['a','b']};s.has_run=lambda k:False
        class Tab: id=42
        s.tabs={'Study Runs':Tab()}
        class Book:
            def batch_update(self,body): self.body=body
        s.book=Book();s.publish('key',{'Study Runs':[['key','=malicious()']]})
        self.assertEqual(s.book.body['requests'][0]['appendCells']['rows'][0]['values'][1]['userEnteredValue'],{'stringValue':'=malicious()'})
        with self.assertRaises(ValueError): s.publish('key',{'Study Runs':[['bad']]})

    def test_daily_end_to_end_fifty_rows_and_frozen_forecast(self):
        import nifty_study.run as run
        day=datetime.fromisoformat('2026-11-09T18:30:00+05:30')
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return day
        daily=[];d=datetime(2026,1,1,tzinfo=IST)
        while d.date()<=day.date():
            if session(str(d.date())):
                i=len(daily);daily.append([int(d.timestamp()),100+i,102+i,99+i,101+i,1000+i])
            d+=timedelta(days=1)
        members=[{'Symbol':f'S{i:02}','Industry':'Test','Series':'EQ'} for i in range(50)]
        class Feed:
            def __init__(self,*a,**kw): pass
            def history(self,*a,**kw):
                if kw.get('resolution')=='15': raise ValueError('Optional intraday absent')
                return daily
        schema=json.loads(Path(run.__file__).with_name('schema.json').read_text())
        published={}
        class Book:
            def has_run(self,key): return False
            def records(self,name): return []
            def publish(self,key,tables):
                for name,rows in tables.items():
                    assert all(len(r)==len(schema[name]) for r in rows),name
                published.update(tables)
        with tempfile.TemporaryDirectory(dir='.') as out:
            with patch.multiple(run,datetime=Clock,Sheets=Book,Fyers=Feed,OUT=Path(out)),patch.object(run,'fetch_universe',return_value=('fixture',members,'fixture')),patch.object(run,'public_get',return_value='<rss/>'),patch.dict('os.environ',{'FYERS_ACCESS_TOKEN':'synthetic'}):
                result=run.execute()
        self.assertEqual(result['status'],'COMPLETED')
        self.assertEqual(len(published['Study Observations']),50)
        forecasts=published['Study Forecasts']
        self.assertEqual(len(forecasts),50)
        self.assertEqual(sum(r[9] for r in forecasts),5)
        self.assertTrue(all(r[2]=='2026-11-11' for r in forecasts))

if __name__=='__main__': unittest.main()

