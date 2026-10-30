"""Compact month snapshots; names/notes are dictionary-encoded, never truncated."""
from comparison_engine import HEADERS,VERSION
COLUMNS=['Date','Family','Expiry Choice','SL %','Variant','Status','Baseline Net','Variant Net','Net Difference','Variant Costs','Net at 2x Cost','Regime','Gap Direction','DTE','Gate Decision','Evaluation Phase','Notes']
CATEGORICAL={'Family','Expiry Choice','Variant','Status','Regime','Gap Direction','Gate Decision','Evaluation Phase','Notes'}
def compact(rows,month):
 dictionaries={k:[] for k in CATEGORICAL};values=[]
 for row in rows:
  r=dict(zip(HEADERS,row));record=[]
  if r.get('Version')!=VERSION or not str(r.get('Date','')).startswith(month):continue
  for c in COLUMNS:
   v=r.get(c,'')
   if c in dictionaries:
    if v not in dictionaries[c]:dictionaries[c].append(v)
    v=dictionaries[c].index(v)
   elif c not in ('Date',):
    try:v=float(v) if str(v).strip() else None
    except (ValueError,TypeError):v=None
   record.append(v)
  values.append(record)
 return {'kind':'month','version':VERSION,'month':month,'columns':COLUMNS,'dictionaries':dictionaries,'values':values}

