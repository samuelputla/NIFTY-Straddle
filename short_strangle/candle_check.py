"""Verify short-option stops with minute highs; retain boundary uncertainty."""
from datetime import datetime
from math import isfinite

PREFIX = 'FYERS Candle Check: '

def check_leg(response, entry_at, stop, day):
    entry = datetime.fromisoformat(entry_at)
    deadline = datetime.fromisoformat(day + 'T15:00:00+05:30')
    if entry.date().isoformat() != day or entry >= deadline or stop <= 0:
        raise ValueError('Invalid audit interval/stop')
    start = int(entry.timestamp()) // 60 * 60
    end = int(deadline.timestamp())
    expected = set(range(start, end, 60))
    bars, invalid = {}, False
    for c in response.get('candles', []) if response.get('s') == 'ok' else []:
        try:
            ts = c[0]
            if not start <= ts < end:
                continue
            if ts not in expected or ts in bars or len(c) < 6:
                invalid = True
                continue
            o,h,l,close = map(float,c[1:5])
            if not all(isfinite(v) and v >= 0 for v in (o,h,l,close)) or not l <= min(o,close) <= max(o,close) <= h:
                invalid = True
                continue
            bars[ts] = (o,h,l,close)
        except (TypeError,ValueError,IndexError):
            invalid = True
    # A bar starting before the actual entry cannot prove an entry-minute hit.
    hits = [ts for ts,b in bars.items() if ts >= entry.timestamp() and b[1] >= stop]
    boundary_hit = start < entry.timestamp() and start in bars and bars[start][1] >= stop
    complete = not invalid and set(bars) == expected
    state = 'STOP HIT' if hits else 'ENTRY MINUTE AMBIGUOUS' if boundary_hit else 'NO STOP HIT' if complete else 'MISSING CANDLES'
    return {'state':state,'first_confirmed_hit':datetime.fromtimestamp(min(hits),entry.tzinfo).isoformat() if hits else '',
            'high':max((b[1] for b in bars.values()),default=None),
            'low':min((b[2] for b in bars.values()),default=None),
            'candles':len(bars),'expected':len(expected),'complete_minutes':complete,
            'entry_minute_ambiguous':boundary_hit,
            'range_basis':'Entry-minute to 14:59 inclusive; entry-minute extrema may precede actual entry'}

def apply_check(row, responses, day):
    r = list(row) + [''] * (28-len(row))
    if not r[10] or not all(r[i] != '' for i in (13,14,15,16)):
        return r, {}
    results = {}
    descriptions = []
    for side,sc,st,xc,tc,rc in (('CE',11,15,17,19,21),('PE',12,16,18,20,22)):
        result = check_leg(responses.get(r[sc],{}),r[10],float(r[st]),day)
        results[side] = result
        descriptions.append(f"{side} High={result['high']} Low={result['low']} {result['state']} [{result['candles']}/{result['expected']} minutes]")
        # Correct a previously missed stop, or an observed stop captured later.
        # Keep original state in before.json. Candle timestamp identifies a minute,
        # not the exact crossing second or an executable fill.
        hit = result['first_confirmed_hit']
        prior_stop = 'SL' in str(r[rc])
        if hit and (not prior_stop or not r[tc] or datetime.fromisoformat(hit) < datetime.fromisoformat(r[tc]).replace(second=0,microsecond=0)):
            r[xc] = float(r[st])
            r[tc] = hit
            r[rc] = 'SL FYERS candle-high threshold paper fill; minute timestamp'
        elif not prior_stop and result['state'] in ('ENTRY MINUTE AMBIGUOUS','MISSING CANDLES'):
            descriptions.append(side + ' stop outcome remains uncertain')
    # Replace only this audit's own note so reruns remain idempotent.
    original = str(r[26]).split(PREFIX)[0].rstrip('; ')
    r[26] = (original + '; ' if original else '') + PREFIX + ' | '.join(descriptions)
    return r, results
