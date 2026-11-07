# Short Term Calls And Tracking

One GitHub workflow generates and journals all qualifying cash-equity Intraday and Swing paper setups from **9 November 2026**. It chooses at most three unique stocks per day, prospectively, for a separate **Rs 300,000** funded paper account. No broker order interface exists.

## Daily Behaviour

The normal generation run is approximately 09:50 IST. GitHub cron is best effort. A delayed run may generate until 11:00; later starts do not issue calls. Tracking runs are scheduled every 15 minutes from 09:35 to 16:20 IST. The existing strategies and schedules are untouched. A repository-wide single-writer concurrency group serializes this workflow's runs. Generated plans and original rules persist in dedicated tabs of the existing Nifty Forward Tests workbook.

Generation evaluates NSE cash EQ securities using six recent official daily bhavcopies and complete opening 09:15–09:45 one-minute FYERS data. Monday's prior price data includes the Sunday 8 November Muhurat session; its short-session volume is excluded from normal-volume comparisons. Missing required daily archives or incomplete opening data prevent unsupported calls. No candidate-count cap is applied. Each eligible stock is evaluated separately for an Intraday and Swing plan. Excluded and rejected candidates and their reasons are retained in the run artifact. No qualified calls is a valid outcome.

This is **Automated Price And Volume Research V1**, a new unvalidated selection experiment. It is not a replication of discretionary analyst judgment or HDFC Securities' algorithm. The earlier discretionary calls did not establish the numerical selection filters below. Fundamentals, news, corporate-action adjustment, volume-at-price profiles and executable spreads/depth are not verified by this version. No win probability is claimed. A corporate action or exceptional event can therefore require manual review before interpreting the research.

## Frozen Selection Assumptions

Eligible shares cost at least Rs50, have at least Rs100 crore of recent normal-session turnover, sufficient six-session data, positive recent momentum and no more than 12% appreciation across that sample. The rank combines close location, relative volume and momentum, with an extension penalty. Funds, ETFs and trusts are excluded by name/series checks. These are research parameters in `config.json`, not proven optimal filters. Liquidity is an initial screening proxy, not an execution guarantee.

Resistance is the greater of the recent three-session high and opening 30-minute high. A 0.05% buffer defines the trigger; the entry band extends 0.15%. Intraday invalidation uses the opening low; Swing invalidation uses recent three-session/opening support. Risk must be between 0.3% and 2.5% for Intraday, or 0.3% and 5% for Swing. Rounding uses a Rs0.05 planning grid, not a claim about the instrument's current exchange tick size. Target 1 is 1R and Target 2 is 2R at the most expensive allowed entry.

Each plan is registered before its future start time, after all generation inputs are available. All calls retain their trigger, band, stop, targets, Enter By, Exit By, observation deadline, source, rationale, selection evidence and immutable hash. Original calls are never silently rewritten. Manually supplied calls can be registered through `plans.json`, provided they remain prospective. Use a new ID for a fresh assessment.

## Entry And Exit

After the frozen start time, a complete exchange-aligned 15-minute candle must close strictly above the trigger. A later candle must retest the band; the retest or a subsequent completed candle must close strictly above the trigger and inside the band. The breakout candle cannot double as the later retest. The next available one-minute open must also be within the band. No touch-only entries or chasing. No entry after 12:30 IST; a stop touch before entry cancels the plan. Partial 15-minute bars are not used.

Paper baseline: **full exit at Target 1**, the original stop, or the time deadline, whichever occurs first. Target 2 is an observation objective, not additional booked profit. Intraday exits by 15:00 that session; Swing exits by 15:00 on the fifth normal session including its issue date. Holidays are excluded. No trailing, averaging, reset or partial-exit convention is implied. Gaps below a stop execute at the worse next minute open in the simulation.

Post-exit observations continue through five normal sessions after the original time deadline. Target 1, Target 2 and original-stop touches are journaled separately and never alter booked P&L. A target reached before a valid entry is a missed move, with a recorded phase such as breakout without retest, retest without valid entry, after cancellation, or after entry expiry. A retest and target within one minute have unknown ordering.

## Two Accounting Views

**All-call research:** every qualified plan is independently reconstructed. Report gross rupees per share and percentage return based on actual simulated entry. Unfilled plans are not wins and have no trade return. All-call totals are not a funded portfolio return.

**Funded paper portfolio:** choose up to three unique stocks per day using the frozen candidate score minus a risk-distance penalty, before outcomes. No hindsight promotion of other calls after a miss. Existing positions/pending reservations consume cash and type slots. Keep at most three open Intraday and three open Swing selections. A 15% initial-capital allocation ceiling, a 0.5% initial-capital planned-risk ceiling including variable friction, and a 10% cash reserve determine integer quantities. No leverage; retained positions can reduce new selections below three. Fixed sizing uses initial capital, while cumulative realized results affect available cash.

Estimated net P&L uses a deliberately explicit illustrative **0.15% of buy turnover + 0.15% of sell turnover + Rs40 per round trip**, including a friction allowance. This is a research proxy, not FYERS' actual brokerage/tax schedule, not a contract-note reconciliation and not a guarantee of slippage. The official fee schedule to consult when replacing it is https://fyers.in/charges-list . Gross and estimated net remain separate. Account realized ROI is cumulative estimated net P&L divided by **Rs300,000**, not the sum of individual trade percentages. Unrealized P&L is shown separately without future exit costs. Uncertain open trades withhold a definitive account ROI.

## Sheets And Evidence

- Short Term Calls: original sealed plans; nonblank quantity identifies a funded portfolio selection.
- Short Term Status: breakout/retest/confirmation, simulated entry/exit, per-share P&L and percentages, estimated total P&L for selected trades, missed moves, post-exit touches and coverage.
- Short Term Events: deduplicated chronological event journal.
- Short Term Runs: workflow health, generation counts, failures and run links.
- Short Term Portfolio: starting capital, cash, deployed/reserved capital, cumulative realized estimated net, account ROI and unrealized gross P&L.

Raw history, daily files, candidate rankings, universe exclusions, selection rejections, frozen new calls and results are preserved as GitHub run artifacts for 90 days. All-event rows use deterministic IDs and fixed-cell retry writes; repeated execution does not append duplicate events. Changed original calls or conflicting previously recorded events stop publication and require review.

Live eligible/open calls are reconstructed on scheduled polls. Unfilled, cancelled and closed calls receive a full-session price-path audit after 15:35, avoiding unnecessary broker requests every poll. Missing normal-session minutes block eligible entries or leave open outcomes under review. Stop and target within the same minute are ambiguous; no assumed winner is booked. MFE/MAE include the exit minute's observed high/low and can include movement after the exact intraminute exit; their column meaning is an observed bound.

This is one-minute historical reconstruction, **not broker fills or second-level live tracking**. Sparse/partial data cannot establish every trade path. FYERS requests are paced by at least 2.1 seconds and stop without retry on rate limits; other workflows can share the same upstream quota. Calendar coverage is verified only for the remaining normal sessions of 2026 and fails closed outside it. Sunday Muhurat is used as price context only; no normal-strategy entry is generated that Sunday.

## Validation

`python -m unittest discover -s short_term_calls/tests -v`

`python -m short_term_calls.tests.http_probe http://127.0.0.1:4922`

The probe uses `postman/mocks/short-term-history/default.js`. This Windows Postman installation cannot start its simulation dataset daemon; use the identical narrow fixture directly or run the HTTP probe in Linux CI. Do not claim a successful Postman simulation run. No real credentials are used in fixture tests. The production connection check retrieves a prior normal equity session and journals success without creating test trades.
