from rolling_engine import *
def at(t):return '2026-10-29T'+t+'+05:30'
def pair(now=0,ce=.51,pe=-.49,strike=22700):return dict(at=now,spot=strike,strike=strike,CE=dict(symbol='CE'+str(strike),price=100,delta=ce),PE=dict(symbol='PE'+str(strike),price=100,delta=pe))
def advance(s,t,p,gs=None):
 quotes={l.symbol:90 for sc in s.scenarios.values() if sc.active for l in sc.active.open_legs()};s.advance(at(t),p,quotes,gs or {},p['at'])
s=Study('Time Based','Current Week','2026-11-03','2026-10-29');advance(s,'09:30:00',pair());s.tick('CE22700',140,at('10:00:00'));advance(s,'11:20:00',pair(1));advance(s,'13:10:00',pair(2));advance(s,'15:00:00',pair(3));assert all(len(sc.cycles)==3 and sc.done for sc in s.scenarios.values());assert len(s.logs())==27;assert s.summary(at('15:00:00'))[-1]==450
s=Study('Delta Based','Current Week','2026-11-03','2026-10-29');advance(s,'09:30:00',pair());advance(s,'10:00:00',pair(1),{'CE22700':.685,'PE22700':-.315});assert len(s.scenarios[25].cycles)==1 # exactly .35: no roll
advance(s,'10:00:01',pair(2,strike=22750),{'CE22700':.69,'PE22700':-.31});assert len(s.scenarios[25].cycles)==2
s.tick('CE22750',150,at('10:05:00'));advance(s,'10:05:01',pair(3,strike=22800),{'CE22750':.70,'PE22750':-.30});assert len(s.scenarios[25].cycles)==3 # original pair triggers reset; survivor alone is closed
advance(s,'11:00:00',pair(4),{'CE22800':.9,'PE22800':-.1});assert len(s.scenarios[25].cycles)==3
s=Study('Delta Based','Monthly','2026-11-23','2026-10-29');advance(s,'09:30:00',pair());s.tick('CE22700',200,at('10:00:00'));s.tick('PE22700',200,at('10:00:01'));advance(s,'10:01:00',pair(1),{'CE22700':.9,'PE22700':-.1});assert len(s.scenarios[25].cycles)==1
assert not valid_pair(pair(),31,True)
print('PASS: timed resets after stops, same-strike re-entry, cycle charges, strict delta threshold, survivor delta, maximum entries, flat stop, stale snapshots')
s=Study('Time Based','Current Week','2026-11-03','2026-10-29');advance(s,'09:30:00',pair());advance(s,'11:21:00',pair(1));advance(s,'13:10:00',pair(2));advance(s,'13:10:01',pair(3));assert all(len(sc.cycles)==2 for sc in s.scenarios.values());assert s.issues==['MISSED RESET 11:20:00']
print('PASS: missed reset cannot consume the next slot twice')

# User's original-pair example: stopped CE remains in signal, never in later P&L.
for choice in CHOICES:
 s=Study('Delta Based',choice,'2026-11-03','2026-10-29');advance(s,'09:30:00',pair())
 s.tick('CE22700',125,at('09:40:00'));old_ce=s.scenarios[25].active.legs['CE'];assert old_ce.exit==125
 advance(s,'10:00:00',pair(1,strike=22800),{'CE22700':.61,'PE22700':-.39})
 assert len(s.scenarios[25].cycles)==1 # pair -0.22 versus reference -0.02 => .20, no false survivor trigger
 advance(s,'10:01:00',pair(2,strike=22900),{'PE22700':-.30})
 assert len(s.scenarios[25].cycles)==1 # missing stopped-leg Greek must block roll
 advance(s,'10:02:00',pair(3,strike=22900),{'CE22700':.70,'PE22700':-.30})
 sc=s.scenarios[25];assert len(sc.cycles)==2
 assert old_ce.exit==125 and old_ce.exit_at==at('09:40:00')
 assert sc.cycles[0].legs['PE'].exit==90 and abs(sc.cycles[0].close_delta+.40)<1e-10
 assert abs(sc.cycles[0].delta_changed-.38)<1e-10
 assert abs(sc.active.reference+.02)<1e-10
 advance(s,'10:03:00',pair(4,strike=22950),{'CE22900':.69,'PE22900':-.31})
 assert len(sc.cycles)==3 # second cycle has its own reference
 advance(s,'10:04:00',pair(5,strike=23000),{'CE22950':.9,'PE22950':-.1})
 assert len(sc.cycles)==3
 advance(s,'15:00:00',pair(6))
 log=next(r for r in s.logs() if r[4]==25 and r[5]==1)
 assert log[23]==-1125 # (-25 CE +10 PE)*65 -150, stopped CE counted once
print('PASS: all expiry variants track stopped-contract delta, require both Greeks, preserve stopped fills/P&L, reset reference and cap entries')
