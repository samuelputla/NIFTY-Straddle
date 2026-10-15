# Weekly NIFTY Strangle — agreed paper rules, version 2

## Scope

Read-only FYERS market data; simulated positions only. No broker order routes.
Only `Nifty Weekly Strangle` and `Nifty Weekly Strangle Logs` are written. Daily
straddle and manual positions are not read, closed, or changed by this strategy.
“Rule compliance” here means conformance to these agreed paper rules; it is not
regulatory certification or a claim that this trading strategy is profitable.

## Entry and rollover

- Track carried premiums from 09:15 IST; initial Tuesday entry aims for 09:30.
- If 09:30 data is unavailable, use the first eligible later observation and
  record its actual capture time. Never relabel a late quote as 09:30.
- Select the next listed NIFTY expiry strictly after the entry date, or strictly
  after the closed expiry when advancing a cycle. Month-end contracts are usable;
  a missing weekly flag must not exclude a holiday-adjusted Monday contract.
- Sell one OTM CE and one OTM PE, each within INR 20–25, closest to INR 25.
  Retry when no eligible pair is available. Paper quantity remains 65 units.
- Roll an active cycle at 09:30 on its actual recorded expiry date. When the
  expiry shifts to Monday, rollover also shifts to Monday. Initial flat-account
  entry remains Tuesday; the holiday rule applies to carried-cycle rollover.

## Adjustments

`divergence = (higher premium - lower premium) / higher premium`.

- Before 15:25, trigger when divergence is **at least 50%**.
- From 15:25 until 15:30, trigger only when divergence is **greater than 80%**.
- Retain the higher-premium leg. Buy back the lower-premium leg **even if that
  realizes a loss** (explicitly confirmed by the user).
- Sell a replacement of the same option type and expiry at **90–95%** of the
  retained premium; prefer the premium nearest 90%.
- The replacement strike must move inward toward the retained strike, may equal
  it, and must never cross it. No eligible replacement means keep the current legs.
- Requote both existing legs and the candidate in one request immediately before
  the simulated roll. Recheck divergence, retained side, band and session cutoff.
- Each adjustment adds INR 150 of estimated costs: INR 75 buyback + INR 75 sale.

## Straddle and cycle exits

- A straddle exists only when CE and PE strikes are equal. Freeze the **current
  combined premiums at formation**, not the retained leg's original sell credit.
- Stop further divergence adjustments. Exit both legs when combined premiums
  reach 110% of that frozen reference.
- After a straddle stop, immediately queue the next-expiry cycle and enter on the
  next eligible data capture during the session. Do not wait until Tuesday.
- Also exit and advance on INR 2,500 **estimated net** profit across every leg,
  or the actual-expiry 09:30 rollover. Fresh exit quotes recheck a profit target
  before executing; stop/expiry exits remain queued through transient failures.
- If an exit completes at session end or the next entry lacks data, persist the
  next-expiry request and resume it next session. Never create overlapping cycles.

## Costs and P&L

The user confirmed **INR 75 per execution of one leg**, i.e. INR 150 for a complete
sell/buyback round trip. `weekly_cost_profile.json` records this all-in assumption.
No extra tax or slippage rate is layered on top. This is a paper estimate, not a
broker contract-note calculation. The profile and quantity are frozen per cycle.

`estimated net = (realized premium points + open premium points) * quantity
                 - costs already incurred - estimated costs to close open legs`

The INR 2,500 target uses this estimated liquidation net. Example: 50 gross
points * 65 = INR 3,250, less four INR 75 executions = INR 2,950: the INR 2,500 target is met.
At two INR 25 initial credits, the no-adjustment maximum is also INR 2,950;
the INR 2,500 net target can therefore be met without adjustments.

Existing historical rows remain unchanged. On first resume, reconstruct paid
costs from that cycle's ledger, reconcile open positions and realized points,
then append a migrated snapshot. Missing/inconsistent ledgers stop migration.
The existing premium-point columns remain **gross premium cashflows**; the rupee
P&L column on version-2 rows is estimated net. `State JSON` identifies its basis,
cost profile, paid costs and rule version. Old rows lack that marker and are gross.
Legacy same-strike positions without a formation-time reference need historical
reconstruction; the program refuses to invent a new reference from startup prices.

## Data and recovery guarantees

- Positive finite prices only. Socket callbacks cache data; the strategy loop
  alone mutates positions. A decision uses a copied paired snapshot.
- Cache observations must be no more than 5 seconds old and no more than 2 seconds
  apart. Stale pairs use a bounded paired REST refresh, at most once per 15 seconds.
- Receipt time is recorded explicitly. A fresh API response is not proof that an
  illiquid contract last traded recently; LTP fills are simulations, not executable
  bid/ask fills. This remains a market-data limitation.
- FYERS reads have a 6-second deadline and a maximum of two unfinished workers.
  Sheets transport uses 3-second connect / 8-second read timeouts.
- Save complete position state and pending event IDs before flushing the event
  ledger. Replay missing event rows by stable ID on restart. An uncertain state
  write halts the worker instead of repeating simulated trades with new IDs.
- Never resurrect an older active state when the newest state is corrupt/closed.
- No new entries, adjustments or exits after the session cutoff. Closing state
  writes may finish shortly afterwards. An exit waiting on data remains queued.

## Runner setup

The default GitHub-hosted workflow schedules at 08:55 IST. The morning job ends
at 12:30; a dependent afternoon job restores saved state and runs to 15:30.
Each has a budget below the hosted six-hour limit. There is only one writer.
The afternoon job requires a successful morning checkpoint; failures require
inspection rather than silently continuing an uncertain state.

**Hosted scheduling and the job handoff can leave monitoring gaps.** This design
does not guarantee 09:15 startup, 09:30 capture or uninterrupted intraday coverage.
The script reports the actual observation times and does not fabricate gap fills.

For a continuous session, register a private Linux self-hosted runner labelled
`weekly-paper`, keep it online, install Python/Node as required by GitHub Actions,
and set repository variable `WEEKLY_DEDICATED_RUNNER=true`. The workflow then uses
one 480-minute session job and disables both hosted jobs. The machine, FYERS login
and network must remain available. Do not enable the variable without a runner.
This change prepares that mode; it does not install a runner or enable it remotely.

Manual dispatch defaults to setup-only. Uncheck setup-only to monitor paper positions.
The end-of-day expiry boundary is taken from FYERS contract metadata. The script
does not maintain an independent exchange holiday calendar for flat-account entry.

## Verification

Run `python -m unittest -v test_weekly_strangle` for offline state, cost, replacement,
stop, rollover, cutoff and persistence scenarios. No credentials or live requests
are used. Passing offline checks does not establish live feed or scheduler readiness.
