"""Read-only accounting audit of saved paper state; no candle reconstruction."""
import json
from collections import Counter
from pathlib import Path
from short_strangle.engine import Scenario, LEVELS, DISTANCES, CHOICES, QTY, COST, summary_rows

def audit(state):
    scenarios = [Scenario(**raw) for raw in state['scenarios']]
    expected = {(d,c,p) for d in DISTANCES for c in CHOICES for p in LEVELS}
    actual = [(s.distance,s.choice,s.pct) for s in scenarios]
    if len(actual) != 81 or set(actual) != expected: raise ValueError('Missing/duplicate scenario configuration')
    for s in scenarios:
        if s.entries and (set(s.entries) != {'CE','PE'} or not '09:30:00' <= s.entry_at[11:19] <= '09:30:30'):
            raise ValueError('Invalid entry capture')
        for side, (price, at, reason) in s.exits.items():
            if not s.entries or at < s.entry_at: raise ValueError('Exit before entry')
            if 'SL threshold' in reason and abs(price-round(s.entries[side]*(1+s.pct/100),2)) > .0001:
                raise ValueError('Stop fill does not reconcile')
    return {'version':'strangle-v1', 'paper_only':True, 'scenarios':81,
            'quantity_assumption':QTY, 'round_trip_cost_assumption':COST,
            'statuses':dict(Counter(s.status for s in scenarios)),
            'summary':summary_rows(scenarios),
            'notes':'Accounting/configuration audit only; no historical candle or executable-fill validation. Exclude INCOMPLETE results from completed-performance analysis.'}

def main():
    folder = Path('short_strangle_output')
    report = audit(json.loads((folder/'state.json').read_text(encoding='utf-8')))
    (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'summary'}))

if __name__ == '__main__': main()
