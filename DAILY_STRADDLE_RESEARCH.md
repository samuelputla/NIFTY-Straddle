# Daily straddle research capture

This is a separate market-data recorder, not a strategy change. It neither
imports `today_test.py` nor changes any core/V2 file, workflow, position, stop,
entry, exit, or benchmark P&L. It contains no order routes. Disable its own
workflow to stop research collection independently.

## Schedule and scope

The independent workflow is queued at 09:00 IST on weekdays. Its preparation job
waits until 09:12; collection finishes at 15:03, leaving time to read the core's
15:00 finalization. GitHub scheduling can be late. Actual start/receipt times and
missing coverage are recorded. A holiday/no-data session is never a completed
trade replay. No past session is relabelled as live capture.

The next normal session after implementation is **21 October 2026**, since
20 October is Dussehra. The four remaining 2026 normal-session closures are
explicitly skipped using NSE F&O circular FAOP71777 (20 October, 10/24 November,
25 December). Review the calendar for 2027 and any subsequent exchange changes;
future years are flagged as needing calendar review. Muhurat/special sessions
are outside this normal-session workflow.

One extra full `SymbolUpdate` socket records NIFTY, India VIX, the exact front
NIFTY futures contract, and at most five nearby CE/PE strike pairs plus the
core's exact CE/PE. Hard limit: 17 active symbols. After the core confirms its
entry, the nearby band is frozen; the chosen core options remain subscribed
through the end even if stopped. The selected contracts come from **read-only**
`Nifty Daily Straddle Logs` rows for today's `SCHEDULED PAPER` run, not from
guessed symbols or the Synthetic-forward strategy. Multiple different core
entries are flagged rather than silently combined.

SymbolUpdate supplies LTP, best bid/ask and quantities, volume, and source times
where FYERS sends them. This is top-of-book data, **not five-level depth or an
exchange tick-by-tick feed**. It cannot establish guaranteed fills or queue
priority. Missing fields remain blank. Both epoch/monotonic receipt times and
the original source timestamps are retained. `last_traded_time` is not a quote
timestamp; quote lag uses `exch_feed_time` only when present.

## Supporting context

- Option-chain snapshots request OI, OI change, previous OI, volume, IV, delta,
  gamma, theta and vega for ATM +/- two strikes. Snapshots are saved every five
  minutes with request parameters and actual receipt times. Best-effort extra
  snapshots are requested around 09:29 and 09:31. These are **pre/post-entry
  context**, not an exact 09:30 Greek/OI measurement. Unsupported/missing Greeks
  remain missing. Selected options outside the current chain range are flagged.
- Exact front futures symbol/expiry comes from `futures_chain`. Its volume is
  streamed; one-minute history is requested with `oi_flag=1, cont_flag=0` about
  every five minutes. OI is called present only if **every returned candle has
  seven fields and a numeric non-negative seventh field**. Empty responses fail
  this check. Zero OI is preserved, not proof of valid trading activity. A new
  day's different contract is a rollover, not an OI change in the old contract.
- Previous trading-day NIFTY daily candles are saved. Completed NIFTY one-minute
  candles are collected about every ten minutes. The 09:15-09:29 opening range
  is populated only with all 15 minute timestamps. Stream-sampled minute paths
  are separately labelled by receipt time and must not replace exchange OHLC.
- The full selected-option stream extends beyond the first stop and retains
  the survivor's path for each core SL scenario. Core Sheet state changes retain
  the core's entry, trigger and exit timestamps; `Observed At IST` is the
  potentially delayed research read time. Do not treat it as the trigger time.
- Event calendar and fee schedule are explicitly **UNCONFIGURED**. This recorder
  does not invent event tags, brokerage/STT/slippage, or execution-adjusted net
  profits. The core's existing benchmark costs remain intact. Research fill
  comparisons require a dated fee schedule, bid/ask freshness/quantity checks,
  and the exact core event times before any cost-adjusted result is published.

## Isolation and account limits

- No shared process, locks, queues, state or Sheet writes with either strategy.
- Research can write only the two research tabs below; it reads the core log.
  No core rows/formulas are rewritten. New worksheet headers must match exactly.
- Broker REST requests are serial, at least 30 seconds apart, capped at 200 per
  run. No extra REST or subscription changes during 09:29:30-09:31:00 or
  14:59:30-15:00:30. SDK reconnect/subscription token mapping can itself make
  requests, beyond this explicit REST counter. Existing subscriptions continue.
- Any broker REST error/timeout disables additional research REST for the
  session. A recognized limit/auth response stops this recorder's socket too.
  No request quota is reset or bypassed. A bounded message queue and 512 MiB
  compressed local storage cap stop this recorder on overflow, marking gaps.
- FYERS quotas are per account: isolation does **not** guarantee zero impact on
  other clients using the same account. Currently the core subscribes two
  options and V2 initially subscribes about 51 symbols; 17 research symbols keep
  their initial combined count below Standard's 100-symbol limit even counted
  conservatively. Other clients or V2 expanding its subscriptions can change
  that. Shared quota headroom and GitHub runner availability remain limitations.

## Outputs

Within the existing spreadsheet:

1. **Daily Straddle Research**: one current session status row per date, actual
   coverage, contracts, quality flags, opening context, OI/Greeks availability,
   and a link to its workflow run.
2. **Daily Straddle Research Events**: research health events and meaningful
   observed changes to each core SL's recorded state. No raw tick spam.

The workflow attaches `daily-straddle-research-RUN-ATTEMPT` for **14 days**:

| File | Contract |
| --- | --- |
| `ticks-*.csv.gz` | One received symbol message per row; `TICK_HEADERS` in source defines columns; missing fields are empty. Preserve arrival order and both time bases. |
| `context-events-*.jsonl.gz` | `{kind, received_at_ist, received_epoch_ns, received_monotonic_ns, data}`. Includes raw read-only REST requests/responses, core checkpoints, and health events. Never includes tokens or SDK authentication payloads. |
| `sampled-1m-*.csv` | Receipt-minute OHLC sample, message count, explicit non-exchange basis; partial minutes are possible. |
| `manifest-*.json` | Version, session statistics, quality flags, Sheet final acknowledgement, file sizes and SHA256 hashes. |

Download these artifacts for longer retention; raw data is never committed to
Git or sent to the dashboard. A rerun is a separate raw segment and is flagged;
the session summary reflects the latest segment, not combined coverage. The
ordinary dashboard sync and UI stay unchanged.

## Verification and activation

Implementation review and Python/YAML static checks do not establish successful
live collection. The first next-session run must show fresh selected CE/PE
messages covering actual entry and exit, saved artifacts, acknowledged research
Sheet updates, and no unexplained gaps before a full-session study is claimed.
No strategy rule is promoted on the strength of this recorder alone.

Workflow activation requires merging the pull request. Existing repository
`FYERS_ACCESS_TOKEN` and `GOOGLE_SERVICE_ACCOUNT_JSON` secrets are reused without
exposing/copying them. No additional secret or broker-order permission is used.

Official interfaces checked 19 October 2026:

- https://fyers.in/api-docs/v3/getting-started/plans-and-limits/
- https://fyers.in/api-docs/v3/api/websockets/data-socket/data-socket-symbol-update/
- https://fyers.in/api-docs/v3/api/market-data/option-chain/
- https://fyers.in/api-docs/v3/api/market-data/futures-chain/
- https://fyers.in/api-docs/v3/api/market-data/historical-data/

Postman API discovery's Orbit service could not resolve on this device; the
official FYERS contracts above and the installed SDK source were used instead.

