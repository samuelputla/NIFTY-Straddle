# NIFTY Next Expiry Straddle — separate paper study

## Expiry rule confirmed on 20 October 2026

Choose the distinct listed NIFTY expiry immediately after the core's nearest
available expiry. Sort actual `expiryData` by date, include contracts expiring
today, collapse duplicate monthly/weekly dates, and select index 1. Never add
seven calendar days, wait for Tuesday, select the third expiry, or fall back to
the nearest contract when the second expiry is unavailable.

| Session | Core reference expiry | This strategy's expiry |
| --- | --- | --- |
| 21 October 2026 | 27 October 2026 | **3 November 2026** |
| 27 October 2026, at 09:30 | 27 October 2026 | **3 November 2026** |
| 28 October 2026 | 3 November 2026 | **9 November 2026**, holiday-shifted listed date |

These examples use the contracts listed when configured. Future sessions always
re-read metadata. Monthly expiry is the weekly occurrence for that week; it is
not excluded merely because it is monthly.

## Frozen baseline mechanics

This standalone script was copied from core `today_test.py`, verified blob
`74d1c9a7dec330a1411de852a4c3fda4e10e4dc7`. The core file is not imported,
modified or executed by this observer. Future core changes do not silently
change this study; compare versions deliberately.

- Nearest-50 spot ATM CE and PE; entry quote requested as close to 09:30 IST as
  possible. Independent preparation can straddle a spot boundary; actual strike,
  quote-request/receipt time and the same late/ATM-shift flags are retained.
- 65 units per leg; seven alternative stop percentages 10/15/20/25/30/35/40.
- Each leg has its own original entry-premium stop. A first stop never moves the
  survivor's stop. No re-entry, rolling, trailing stop, hedge, or combined target.
- Remaining legs exit at 15:00 IST, using the same core closing-quote/fallback
  rules. Threshold paper fills remain the core benchmark, not executable fills.
- Same ₹150 combined daily round-trip charge assumption and ₹250,000 study
  capital denominator. These are benchmark assumptions, not audited margin,
  lot-size history, broker fees or a claim of equal rupee risk across expiries.
- OI/VIX/day-open are supporting data, never entry gates. New optional metadata
  begins 20 seconds after this observer's premium capture; opening history starts
  after 25 seconds, reducing the shared-account 09:30 REST burst. Their actual
  timestamps remain visible. OI requests use the selected expiry as well.

## Contract and operational isolation

The requested expiry is passed to FYERS using its returned `expiry` epoch in
the option-chain `timestamp` parameter. Every selected CE/PE is cross-checked
against FYERS' public `NSE_FO.csv`: expiry epoch column 8, exact symbol column 9,
strike column 15, and CE/PE column 16 (zero-based). Discovery must agree with the
contract master. A chain which ignores the requested expiry cannot create an
entry. Exact symbols come from returned data, never string construction.

Its own process, concurrency group, Sheet rows and two-option subscription keep
position state separate. FYERS account quotas and GitHub runners are still
shared resources; zero indirect impact cannot be guaranteed. Optional requests
are deferred, but core/V2 quotas are not changed by this PR. No order API exists.

The workflow follows the core's 08:55 IST queue time and separate wait job to
09:15, keeping monitoring below GitHub's six-hour job cap. Known remaining 2026
F&O holidays and weekends are skipped by this observer; review future-year and
special-session calendars. GitHub can start late: actual capture time is shown,
not invented as 09:30. The core's scheduling is untouched.

## Separate data and dashboard

- `Next Expiry Straddle`: same 66-column daily schema, separate rows and results.
- `Next Expiry Straddle Logs`: same 29-column per-SL schema, separate run type.
- `Next Expiry Straddle` dashboard navigation: own snapshot, endpoint, dates,
  comparisons, exports and journal. Existing core and Synthetic-forward results
  remain in their existing snapshots. The refresh button reads all three tabs;
  scheduled dashboard sync adds this tab after existing core/V2 uploads.
- No historical results are fabricated. First forward paper observation is the
  next eligible market session after merge. Source Sheet tabs begin headers-only.

## Checks and limits

Python compilation, AST comparison of unchanged mechanics, dashboard TypeScript
and production build are static checks. No integration/market-session tests
were requested or run. Exact selected-expiry live response, 09:30 timing, fresh
quotes, shared quota coexistence and finalization require first-session evidence.
Do not treat the farther expiry as a proven improvement; compare net outcomes,
rupee risk, drawdown, worst day and fills before drawing a conclusion.

References:
- https://fyers.in/api-docs/v3/api/market-data/option-chain/
- https://public.fyers.in/sym_details/NSE_FO.csv
- https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf

