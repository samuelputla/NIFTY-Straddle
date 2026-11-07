"""Deterministic, lag-aware features. Percentages are percentage points."""
import hashlib
import json
import math
from statistics import mean
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
RULE = 'price-volume-v1'
TOP = 5
RULE_SPEC = {'version': RULE, 'top': TOP, 'weights': {'rs20': 2, 'momentum20': 1,
             'rvol20': 1, 'structure': 1, 'sector20': 1}, 'ties': 'symbol ascending',
             'missing': 'no forecast if any required daily series is incomplete'}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def ema(values, window):
    if not values:
        return []
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + 2 / (window + 1) * (v - out[-1]))
    return out

def wilder(values, window):
    if len(values) < window:
        return []
    out = [mean(values[:window])]
    for v in values[window:]:
        out.append((out[-1] * (window - 1) + v) / window)
    return out

def validate_candles(candles):
    if not isinstance(candles, list) or not candles:
        raise ValueError('Missing candle array')
    seen = set()
    for c in candles:
        if len(c) < 6 or not all(isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x) for x in c[:6]):
            raise ValueError('Malformed candle')
        if c[0] in seen or c[5] < 0 or not 0 < c[3] <= min(c[1], c[4]) <= max(c[1], c[4]) <= c[2]:
            raise ValueError('Duplicate timestamp or invalid OHLCV')
        seen.add(c[0])
    return sorted(candles)

def daily_features(bars, benchmark):
    bars = validate_candles(bars)
    if len(bars) < 100:
        raise ValueError('At least 100 completed daily candles required')
    closes = [b[4] for b in bars]
    if any(b[5] <= 0 for b in bars[-21:]):
        raise ValueError('Missing/zero equity volume in required window')
    o, h, low, c, vol = bars[-1][1:6]
    prev = closes[-2]
    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    up = wilder([max(x, 0) for x in changes], 14)[-1]
    down = wilder([max(-x, 0) for x in changes], 14)[-1]
    rsi = 50 if up == down == 0 else 100 if down == 0 else 100 - 100/(1+up/down)
    tr, plus, minus = [], [], []
    for a, b in zip(bars, bars[1:]):
        tr.append(max(b[2]-b[3], abs(b[2]-a[4]), abs(b[3]-a[4])))
        u, d = b[2]-a[2], a[3]-b[3]
        plus.append(u if u > d and u > 0 else 0)
        minus.append(d if d > u and d > 0 else 0)
    smooth_tr, smooth_p, smooth_m = wilder(tr, 14), wilder(plus, 14), wilder(minus, 14)
    dx = [100*abs(p-m)/(p+m) if p+m else 0 for p, m in zip(smooth_p, smooth_m)]
    macd = [a-b for a,b in zip(ema(closes,12),ema(closes,26))]
    resistance, support = max(b[2] for b in bars[-21:-1]), min(b[3] for b in bars[-21:-1])
    momentum = 100*(c/closes[-21]-1)
    benchmark_by_day = {datetime.fromtimestamp(b[0],IST).date():b[4] for b in benchmark}
    def index_close(bar):
        return benchmark_by_day[datetime.fromtimestamp(bar[0],IST).date()]
    rs = momentum - 100*(index_close(bars[-1])/index_close(bars[-21])-1)
    hh, ll = max(b[2] for b in bars[-14:]), min(b[3] for b in bars[-14:])
    # Explicit experimental order-block definition, confirmed only at latest close.
    zone = ''
    if c > max(b[2] for b in bars[-6:-1]) and c-o > smooth_tr[-1]:
        bearish = [b for b in bars[-6:-1] if b[4] < b[1]]
        if bearish:
            zone = f'{bearish[-1][3]:.2f}-{bearish[-1][2]:.2f}; confirmed latest close; experimental'
    weeks = {}
    for b in bars:
        y,w,_ = datetime.fromtimestamp(b[0],IST).date().isocalendar()
        weeks[(y,w)] = b[4]
    # Last two completed prior ISO weeks; exclude current partial week consistently.
    wk = list(weeks.values())[:-1]
    return {'return':100*(c/prev-1), 'gap':100*(o/prev-1), 'intraday':100*(c/o-1),
            'close':c, 'volume':vol, 'rvol20':vol/mean(b[5] for b in bars[-21:-1]),
            'sma20':mean(closes[-20:]), 'sma50':mean(closes[-50:]), 'rsi14':rsi,
            'macd':macd[-1], 'signal':ema(macd,9)[-1], 'atr14':smooth_tr[-1],
            'adx14':wilder(dx,14)[-1], 'stoch14':100*(c-ll)/(hh-ll) if hh>ll else 50,
            'resistance':resistance, 'support':support, 'breakout':c>resistance,
            'momentum20':momentum, 'rs20':rs, 'structure':c/mean(closes[-20:])-1,
            'weekly':100*(wk[-1]/wk[-2]-1) if len(wk)>=2 else None, 'zone':zone}

def intraday_features(bars):
    bars = validate_candles(bars)
    if not bars or sum(b[5] for b in bars) <= 0:
        raise ValueError('Intraday volume unavailable')
    total = sum(b[5] for b in bars)
    typical = [(b[2]+b[3]+b[4])/3 for b in bars]
    vwap = sum(p*b[5] for p,b in zip(typical,bars))/total
    lo, hi = min(b[3] for b in bars), max(b[2] for b in bars)
    width = (hi-lo)/24 if hi>lo else 1
    bins = [0]*24
    # Approximation: entire 15-minute candle volume assigned to typical-price bin.
    for p,b in zip(typical,bars):
        bins[min(23,int((p-lo)/width))] += b[5]
    poc = lo+(max(range(24),key=lambda i:bins[i])+.5)*width
    trend15 = 100*(bars[-1][4]/bars[-2][4]-1) if len(bars)>1 else None
    # Last up-to-60 minutes ending at the final observed bar, not a resampled candle.
    trend60 = 100*(bars[-1][4]/bars[-4][1]-1) if len(bars)>=4 else None
    return {'trend15':trend15,'trend60':trend60,'vwap':vwap,'poc':poc}

def ranked(rows, metric):
    return sorted(rows, key=lambda r:(-r[metric],r['symbol']))

def screen(rows):
    for metric, weight in RULE_SPEC['weights'].items():
        values = [r[metric] for r in rows]
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
            raise ValueError('Required ranking metric unavailable')
        for r in rows:
            less = sum(v < r[metric] for v in values)
            equal = sum(v == r[metric] for v in values)
            part = (less+(equal-1)/2)/(len(rows)-1) if len(rows)>1 else .5
            r.setdefault('parts',{})[metric]=part
    for r in rows:
        r['score']=sum(r['parts'][m]*w for m,w in RULE_SPEC['weights'].items())/sum(RULE_SPEC['weights'].values())
    return ranked(rows,'score')

def review_outcome(selected, actual_rank):
    return 'HIT' if selected and actual_rank<=TOP else 'FALSE POSITIVE' if selected else 'MISSED LEADER' if actual_rank<=TOP else 'CONTROL'
