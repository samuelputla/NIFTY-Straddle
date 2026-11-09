# Short Strangle Paper Research

Separate project module and workflow; existing straddle engines, Sheet tabs and validation are untouched. This supersedes the earlier request for four unspecified straddle additions. There are nine distance/expiry studies with nine independent stops each: **81 paper scenarios**, not 13 combined strategies.

## Frozen Rules — Strangle V1

- Capture actual NIFTY spot from the first quote response at/after 09:30 IST (latest 09:30:20). Use the same frozen spot for all studies. Never recalculate strikes during the day.
- CE = spot × (1 + distance/100); PE = spot × (1 − distance/100). Distances: 1%, 1.5%, 2%. Round each result independently to nearest 100; exact half rounds upward. Example: 25,000 spot at 1% gives 25,300 CE / 24,800 PE. Actual distances differ after rounding.
- Current Week = first listed unexpired option expiry (including today); Next Week = next listed expiry; Monthly = earliest unexpired futures expiry also verified in options metadata/master. Identical expiry dates may legitimately appear under multiple choices; these remain independent studies.
- Exact rounded contracts must exist in the FYERS master; no guessed symbols or substitute strikes.
- Enter both shorts using positive socket marks received within ten seconds, by 09:30:30. Record actual capture time. The thirty-second grace is operational, not a claim of exact 09:30 execution. Missed entries remain blank, not zero-profit days.
- Each leg independently stops at its own entry premium × (1 + SL/100). Nine parallel SLs: 10,15,20,25,30,35,40,45,50%. Stops fill at the rounded threshold as in the original paper project. A stopped leg stays closed. No re-entry or resets.
- At 15:00, surviving legs exit using a new REST quote response; record actual receipt time. Missing final marks leave unresolved positions and blank net P&L.
- Quantity 65 per leg and INR150 round-trip assumed costs per entered scenario match the original project for comparison. These are paper assumptions, not verified current contract lots, actual charges or margin. Never add the 81 alternative outcomes as simultaneous portfolio profit.
- Unhedged short strangles have no guaranteed maximum loss. Stops can gap and threshold fills can overstate performance. COMPLETED means both paper exits, their timestamps/reasons, and net P&L are filled; it does not certify market-data coverage. Quote/socket/processing gaps remain in Coverage Notes even after completion. Exclude those scenarios from clean performance analysis. Missing exits remain INCOMPLETE. This engine cannot establish tick-complete market coverage or executable fills. No real orders are supported.

## Workbook And Quotas

Workbook: [Nifty Forward Tests](https://docs.google.com/spreadsheets/d/1yWpG7oLIpdT7MeX9yRQb6c1jTKXcfCDt4mH_x6mpeWI/edit).

Two dedicated tabs: **Short Strangle Summary** (9 rows/session) and **Short Strangle Logs** (81 rows/session). Summary contains all nine stop-level net outcomes; Logs contain frozen spot, exact contracts, entry, both stops, each exit/reason, status, charges and quantity.

One startup batch read; one reservation write before any entries; one combined two-range values batch per minute; one final batch. Stop events only change memory. No per-tick Sheet calls. A single background writer keeps Sheet delays out of quote processing. Transient quota/server failures use the repository's bounded exponential backoff with jitter, and retry the same cells, never append. Final failures retain recoverable state in workflow artifacts. Quotas are shared with other projects and cannot be guaranteed; this adds approximately one write/minute, not 81 writes/event.

Existing same-day rows block a restart, including partial sessions. Never clear them to force a new entry. Grid capacity expands in chunks before writing. Initial grids are bounded; no other tabs are modified.

## Automation And Evidence

The separate `short-strangle-close.yml` runs at 15:05 IST weekdays (best effort) and shares the collector's concurrency group. It only reconciles existing sessions, never enters positions. It fetches FYERS 15:00 one-minute reference prices, retains all existing observed/stop exits, and recovers wholly missing exits using the exact 15:00 candle OPEN only. Recovered marks are explicitly labelled as simulated recovery proxies, not exact tick fills. No later candle or current quote substitutes for a missing 15:00 candle. Complete scenarios and summary groups become COMPLETED while retaining coverage notes. Missing or partial exit records remain unresolved. Before/after evidence and FYERS reference responses are retained as artifacts for 30 days. Manual dispatch accepts an existing session date; the scoped `.automation/short-strangle-close.json` push trigger checks today's existing session.

Dedicated `short-strangle.yml` uses existing FYERS and Google service-account repository secrets with a distinct concurrency group. Schedule 09:10 IST weekdays, best effort; delayed starts after 09:30:20 refuse entries. Verified repository session calendar fails closed outside its supported period. No existing workflow is changed. An additional socket shares account limits with existing collectors; first-session provider capacity must be observed.

Run local checks: `python -m unittest discover -s short_strangle -p 'test_*.py'`.

Normal collection: `python -u -m short_strangle.collector` through GitHub Actions only. Requires dedicated workbook headers to exist first. State JSON and received quote JSONL are retained as workflow artifacts for 30 days. `python -m short_strangle.report` checks saved scenario coverage, entry windows, exit chronology and threshold fill reconciliation, and writes a status/summary report. It does not reconstruct historical candles or prove execution quality. The existing historical straddle audit retains its original scope. Future live paper sessions are needed to verify provider and Sheet integration.
