from rolling_engine import *
def at(t):return '2026-10-29T'+t+'+05:30'
def pair(now=0,ce=.51,pe=-.49,strike=22700):return dict(at=now,spot=strike,strike=strike,CE=dict(symbol='CE'+str(strike),price=100,delta=ce),PE=dict(symbol='PE'+str(strike),price=100,delta=pe))
def advance(s,t,p,gs=None):
 quotes={l.symbol:90 for sc in s.scenarios.values() if sc.active for l in sc.active.open_legs()};s.advance(at(t),p,quotes,gs or {},p['at'])
s=Study('Time Based','Current Week','2026-11-03','2026-10-29');advance(s,'09:30:00',pair());s.tick('CE22700',140,at('10:00:00'));advance(s,'11:20:00',pair(1));advance(s,'13:10:00',pair(2));advance(s,'15:00:00',pair(3));assert all(len(sc.cycles)==3 and sc.done for sc in s.scenarios.values());assert len(s.logs())==27;assert s.summary(at('15:00:00'))[-1]==450
s=Study('Delta Based','Current Week','2026-11-03','2026-10-29');advance(s,'09:30:00',pair());advance(s,'10:00:00',pair(1),{'CE22700':.685,'PE22700':-.315});assert len(s.scenarios[25].cycles)==1 # exactly .35: no roll
advance(s,'10:00:01',pair(2,strike=22750),{'CE22700':.69,'PE22700':-.31});assert len(s.scenarios[25].cycles)==2
s.tick('CE22750',150,at('10:05:00'));advance(s,'10:05:01',pair(3,strike=22800),{'PE22750':-.49});assert len(s.scenarios[25].cycles)==3 # surviving leg triggers reset
advance(s,'11:00:00',pair(4),{'CE22800':.9,'PE22800':-.1});assert len(s.scenarios[25].cycles)==3
s=Study('Delta Based','Monthly','2026-11-23','2026-10-29');advance(s,'09:30:00',pair());s.tick('CE22700',200,at('10:00:00'));s.tick('PE22700',200,at('10:00:01'));advance(s,'10:01:00',pair(1),{'CE22700':.9,'PE22700':-.1});assert len(s.scenarios[25].cycles)==1
assert not valid_pair(pair(),31,True)
print('PASS: timed resets after stops, same-strike re-entry, cycle charges, strict delta threshold, survivor delta, maximum entries, flat stop, stale snapshots')
s=Study('Time Based','Current Week','2026-11-03','2026-10-29');advance(s,'09:30:00',pair());advance(s,'11:21:00',pair(1));advance(s,'13:10:00',pair(2));advance(s,'13:10:01',pair(3));assert all(len(sc.cycles)==2 for sc in s.scenarios.values());assert s.issues==['MISSED RESET 11:20:00']
print('PASS: missed reset cannot consume the next slot twice')
