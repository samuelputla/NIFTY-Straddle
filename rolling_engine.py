"""Pure paper-only state machine; no broker or network operations."""
import math
from dataclasses import dataclass,field,asdict
LEVELS=(10,15,20,25,30,35,40,45,50)
QTY=65
CYCLE_COST=150
DELTA_TRIGGER=.35
START_DATE='2026-10-29'
CHOICES=('Current Week','Next Week','Monthly')
SUMMARY_HEADERS=['Date','Family','Expiry Choice','Expiry','Entry Time','Entry Spot','India VIX','Status','Last Update','Data Status']+[f'{p}% Profit' for p in LEVELS]+[f'{p}% Cycles' for p in LEVELS]+[f'{p}% Charges' for p in LEVELS]
LOG_HEADERS=['Event ID','Date','Family','Expiry Choice','SL %','Cycle','Expiry','Strike','Entry Time','Entry Spot','Reference Delta','CE Symbol','PE Symbol','CE Entry','PE Entry','CE Exit','PE Exit','CE Exit Time','PE Exit Time','CE Exit Reason','PE Exit Reason','CE Points','PE Points','Net P&L','Charges','Close Time','Close Delta','Delta Changed','Data Status']
def good(v):return isinstance(v,(int,float)) and math.isfinite(v)
def net_delta(pair):return -sum(pair[s]['delta'] for s in ('CE','PE'))
def valid_pair(pair,now,greeks=False):
 return bool(pair) and 0<=now-pair.get('at',-1e10)<=30 and all(good(pair[s].get('price')) and pair[s]['price']>0 and pair[s].get('symbol') for s in ('CE','PE')) and (not greeks or all(good(pair[s].get('delta')) and -1<=pair[s]['delta']<=1 for s in ('CE','PE')))
@dataclass
class Leg:
 symbol:str
 entry:float
 stop:float
 exit:float|None=None
 exit_at:str=''
 reason:str=''
 observed_stop:float|None=None
 def close(self,price,at,reason):
  if self.exit is None:self.exit=price;self.exit_at=at;self.reason=reason
@dataclass
class Cycle:
 number:int
 strike:int
 entry_at:str
 entry_spot:float
 reference:float|None
 legs:dict
 close_at:str=''
 close_delta:float|None=None
 delta_changed:float|None=None
 measurement:dict=field(default_factory=dict)
 def open_legs(self):return [l for l in self.legs.values() if l.exit is None]
@dataclass
class Scenario:
 pct:int
 cycles:list=field(default_factory=list)
 done:bool=False
 missed_slots:list=field(default_factory=list)
 handled_slots:list=field(default_factory=list)
 @property
 def active(self):return self.cycles[-1] if self.cycles else None
@dataclass
class Study:
 family:str
 choice:str
 expiry:str
 day:str
 scenarios:dict=field(default_factory=lambda:{p:Scenario(p) for p in LEVELS})
 issues:list=field(default_factory=list)
 initial_spot:float|None=None
 initial_at:str=''
 vix:float|None=None
 def issue(self,text):
  if text not in self.issues:self.issues.append(text)
 def enter(self,sc,pair,at):
  ref=net_delta(pair) if all(good(pair[s].get('delta')) for s in ('CE','PE')) else None
  sc.cycles.append(Cycle(len(sc.cycles)+1,pair['strike'],at,pair['spot'],ref,{s:Leg(pair[s]['symbol'],pair[s]['price'],round(pair[s]['price']*(1+sc.pct/100),2)) for s in ('CE','PE')}))
  if not self.initial_at:self.initial_at=at;self.initial_spot=pair['spot']
 def tick(self,symbol,price,at):
  if not good(price) or price<=0 or at[11:19]>='15:00:00':return
  for sc in self.scenarios.values():
   if sc.done or not sc.active:continue
   for leg in sc.active.open_legs():
    if leg.symbol==symbol and price>=leg.stop:
     leg.observed_stop=price;leg.close(leg.stop,at,'SL threshold paper fill')
 def close(self,sc,quotes,at,reason,delta=None):
  cy=sc.active
  for leg in cy.open_legs():leg.close(quotes[leg.symbol],at,reason)
  cy.close_at=at;cy.close_delta=delta
  cy.delta_changed=abs(delta-cy.reference) if good(delta) and good(cy.reference) else None
 def observe_delta(self,at,greeks,sample_at):
  if self.family!='Delta Based':return
  for sc in self.scenarios.values():
   cy=sc.active
   if not cy or cy.close_at or cy.reference is None:continue
   if not all(l.symbol in greeks and good(greeks[l.symbol]) and -1<=greeks[l.symbol]<=1 for l in cy.legs.values()):continue
   m=cy.measurement
   if m.get('at')==sample_at:continue
   ce,pe=(greeks[cy.legs[x].symbol] for x in ('CE','PE'));net=-ce-pe;change=abs(net-cy.reference)
   from datetime import datetime
   gap=max(0,(datetime.fromisoformat(sample_at)-datetime.fromisoformat(m.get('at',cy.entry_at))).total_seconds())
   m.update(at=sample_at,ce=ce,pe=pe,net=net,change=change,min=min(m.get('min',net),net),max=max(m.get('max',net),net),max_change=max(m.get('max_change',0),change),count=m.get('count',0)+1,gap=max(m.get('gap',0),gap))
   if change>DELTA_TRIGGER+1e-12 and not m.get('cross_at'):m.update(cross_at=sample_at,cross_net=net,cross_change=change)
 def advance(self,at,pair,quotes,greeks,now):
  clock=at[11:19]
  for sc in self.scenarios.values():
   if sc.done:continue
   if clock>='15:00:00':
    if sc.active and sc.active.open_legs():
     if not all(l.symbol in quotes for l in sc.active.open_legs()):self.issue('Missing final quote; unresolved position');continue
     self.close(sc,quotes,at,'15:00 EXIT',sc.active.measurement.get('net'))
    elif sc.active and not sc.active.close_at:sc.active.close_at=at
    sc.done=True;continue
   if not sc.active:
    if '09:30:00'<=clock<='09:35:00' and valid_pair(pair,now,self.family=='Delta Based'):self.enter(sc,pair,at)
    elif clock>'09:35:00':sc.done=True;self.issue('MISSED ENTRY WINDOW')
    continue
   cy=sc.active
   if self.family=='Time Based':
    for slot in ['11:20:00','13:10:00']:
     number=2 if slot=='11:20:00' else 3
     if clock>=slot and slot not in sc.handled_slots:
      late=(int(clock[:2])*3600+int(clock[3:5])*60+int(clock[6:]))-(int(slot[:2])*3600+int(slot[3:5])*60)
      if late>30:sc.missed_slots.append(slot);sc.handled_slots.append(slot);self.issue('MISSED RESET '+slot);continue
      if not valid_pair(pair,now) or not all(l.symbol in quotes for l in cy.open_legs()):continue
      self.close(sc,quotes,at,'TIME RESET');self.enter(sc,pair,at);sc.handled_slots.append(slot);break
   else:
    opened=cy.open_legs()
    if not opened or len(sc.cycles)>=3:continue
    # Signal uses BOTH original contracts, including a leg already stopped out.
    # Only surviving positions are closed or contribute further open P&L.
    tracked=cy.legs.values()
    if not all(l.symbol in greeks and good(greeks[l.symbol]) and -1<=greeks[l.symbol]<=1 for l in tracked):continue
    current=-sum(greeks[l.symbol] for l in cy.legs.values())
    if abs(current-cy.reference)<=DELTA_TRIGGER+1e-12:continue
    if not valid_pair(pair,now,True) or abs(net_delta(pair))>=abs(current):continue
    if not all(l.symbol in quotes for l in opened):continue
    self.close(sc,quotes,at,'DELTA RESET',current);self.enter(sc,pair,at)
 def summary(self,at):
  complete=all(s.done for s in self.scenarios.values());status='COMPLETED' if complete and not self.issues else 'INCOMPLETE' if self.issues else 'RUNNING'
  row=[self.day,self.family,self.choice,self.expiry,self.initial_at,self.initial_spot if self.initial_spot is not None else '',self.vix if self.vix is not None else '',status,at,'; '.join(self.issues) or 'Observed paper quotes; threshold SL fills; unscaled delta; no orders']
  for sc in self.scenarios.values():
   settled=bool(sc.cycles) and all(l.exit is not None for c in sc.cycles for l in c.legs.values())
   row.append(round(sum(round(l.entry-l.exit,2)*QTY for c in sc.cycles for l in c.legs.values())-len(sc.cycles)*CYCLE_COST,2) if settled else '')
  row += [len(s.cycles) for s in self.scenarios.values()]+[len(s.cycles)*CYCLE_COST for s in self.scenarios.values()]
  return row
 def logs(self):
  rows=[]
  for sc in self.scenarios.values():
   for c in sc.cycles:
    if not c.close_at and self.family!='Delta Based':continue
    ce,pe=c.legs['CE'],c.legs['PE']
    points=[round(l.entry-l.exit,2) if l.exit is not None else '' for l in (ce,pe)]
    settled=all(l.exit is not None for l in (ce,pe))
    status=list(self.issues)
    if not c.close_at:status.insert(0,'OPEN CYCLE' if c.open_legs() else 'FLAT; awaiting session finalization')
    rows.append([f'{self.day}|{self.family}|{self.choice}|{sc.pct}|{c.number}',self.day,self.family,self.choice,sc.pct,c.number,self.expiry,c.strike,c.entry_at,c.entry_spot,c.reference if c.reference is not None else '',ce.symbol,pe.symbol,ce.entry,pe.entry,ce.exit if ce.exit is not None else '',pe.exit if pe.exit is not None else '',ce.exit_at,pe.exit_at,ce.reason,pe.reason,*points,round(sum(points)*QTY-CYCLE_COST,2) if settled else '',CYCLE_COST,c.close_at,c.close_delta if c.close_delta is not None else '',c.delta_changed if c.delta_changed is not None else '', '; '.join(status)])
  return rows


