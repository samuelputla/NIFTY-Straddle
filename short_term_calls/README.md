# Short Term Calls And Tracking

One GitHub workflow uses only the existing **Short Term Calls**, **Short Term Status**, **Short Term Events**, **Short Term Runs** and **Short Term Portfolio** tabs in Nifty Forward Tests. Other strategies/tabs are not changed.

## Daily Operation

- **Phase 1 — Next-Session Shortlist:** prepare the next trading session after 18:05 IST, with 08:50 / 09:05 IST recovery attempts if preparation was unavailable. Track the frozen shortlist during market hours. NSE holidays are respected, including 10 November 2026.
- **Phase 2 — Market-Hours Scanner:** rescreen on each scheduled poll during 09:50–14:30 IST and log additional qualifying swing setups. Each 15-minute scan window is idempotent; existing symbol/session calls are retained without duplicates. Use only completed opening-range and recent minute evidence; original daily indicators remain lagged. The actual registration timestamp is the issue time; no backdated fills.
- Poll market paths every 15 minutes from approximately 09:20–15:35, with a later reconciliation and evening review. GitHub schedules are best effort, not a guaranteed real-time feed.
- **No daily call quota. Every qualifying setup is logged and tracked at exactly one share.** All calls show gross rupees per share, gross trade P&L and percentage return. Unfunded calls remain one-share research observations; portfolio accounting reserves unleveraged cash against the existing Rs300000 paper balance.
- New automated calls are Swing only. Existing frozen Intraday/Swing records retain their original levels, rules, quantities and deadlines.

## Radar And Selection

The whole-NSE six-session archive prefilter excludes funds/trusts, stocks below Rs50, turnover below Rs100 crore, nonpositive momentum and extended five-session rallies. All matching stocks enter the indicator radar; there is no top-30 scan cap. This is a defined liquid-stock universe, not every listed security.

For each covered stock, collect a coherent FYERS daily series with at least 60 observations and a matching 20-session NIFTY50 benchmark window. Record SMA20/50, Wilder RSI14/ATR14, MACD12/26/9, normal-session RVOL20 and relative return. Special-session prices remain relevant to resistance, but Muhurat volume is excluded from normal-volume averages. Missing fields exclude a stock with an explicit reason, rather than silently changing the score. Prior-session feature snapshots can be reused during the same target session; intraday observations never enter an earlier forecast.

The experimental screen requires close above SMA20/50, RSI50–68, positive MACD versus signal, RVOL at least 1, extension at most 8% above SMA20 and 20-session excess return no worse than -5 percentage points versus NIFTY50. Positive excess is labelled Continuation; other passing setups are Recovery, not market leaders. Rank uses relative return with the existing modest risk-distance penalty, only for prospective paper cash assignment; the call count is unlimited.

Configured official event blackouts are explicit. This is not a complete news/earnings or fundamental valuation feed; no causal or institutional-flow claim is inferred from indicators. Calendar coverage ends in 2026 and fails closed afterwards.

## Entry, Exit And Evidence

New V3 calls require a **completed 15-minute breakout close, a later completed retest bar, completed in-band confirmation, and a later actual one-minute open inside the buy band**. The breakout bar cannot double as its retest. Intraday-issued calls require new evidence after their frozen monitoring start, not an earlier morning breakout. A gap above the band is not a fill; support invalidation after issue cancels a pending market-hours call. Shortlist entries expire at 12:30 IST; market-hours calls expire at 15:00 IST, leaving time for fresh confirmation after the final scan.

Premarket levels use recent three-normal-session resistance plus any intervening special-session high, a 0.1% trigger buffer, 0.25% entry band, and previous normal-session low minus 0.1% for the proposed stop. Market-hours calls also incorporate the completed opening range; all level changes occur before issuance. Risk must lie within 1–5.5% at the maximum entry. These are experimental definitions, not a recovered HDFC algorithm or executable exchange tick specification.

T1 is approximately 1R; T2 approximately 2R. **Full exit at T1**, original stop or the 14-calendar-day deadline at 15:00, whichever occurs first; non-session deadlines roll back to the preceding session. T2 and subsequent original-level touches are observations only and never increase booked profit. Continue observations through five normal sessions after the original deadline.

The three chat forecasts for **11 November 2026** are imported from the original sealed shortlist with their exact entry/stop/target/expiry levels. They keep the originally issued **breakout-confirmation-only** rule; their history is not rewritten to impose a retest. They are registered before the target session, or explicitly marked missed installation without fabricated history.

Completed one-minute candles reconstruct price sequences; these are paper simulations, not broker fills. Missing candles and ambiguous stop/target ordering produce review states. Gaps can exit worse than the planned stop. Fees/slippage are unknown, not assumed zero, and net fields remain blank. Quotes and true order execution are not used to claim fills.

## Sheet Logs And Learning

- **Calls:** immutable sealed plan, original levels, entry rule, features, version and one-share selection.
- **Status:** current setup state, entry/exit, gross rupees/percentage/R, missing data and post-exit observations.
- **Events:** entries/exits, all radar feature snapshots/rejections, unfilled/missed targets, stop/data reviews, retrospective market-leader coverage and pattern-change proposals.
- **Runs:** preparation, live generation, tracking, failures, source coverage and connection checks.
- **Portfolio:** existing paper-account summary; all observations retain one-share quantities.

Evening coverage compares the top positive close-to-close liquid NSE movers with the original frozen radar. Outside-radar moves are labelled **formation unknown**; their daily gains are not invented trade profits. Qualified-but-unfunded calls are still replayed and logged.

Stop reviews preserve the original plan and record evidence, gaps, initial volume/relative strength, missed entries and later target touches. The company-news cause remains unresolved unless independently verified. The code emits challenger cohorts such as higher RVOL or positive-relative-strength-only, including removed trades, sample sizes and session counts. These are descriptive cohorts, not counterfactual backtests. **No automatic predictive-rule promotion or source-code rewrite follows a loss.** Correct demonstrated implementation/data errors directly; test predictive changes under a separately frozen rule and chronological holdout/forward evaluation before promotion. Preserve both winners and losers.

All writes use stable identities and fixed-cell idempotence. The five existing tabs expand their row capacity when needed; no new tabs are introduced. Provider credentials are never printed or written to evidence. The desktop Kite session is not a GitHub-runner fallback; unsupported authentication is logged, not bypassed.

## Validation

Run `python -m unittest discover -s short_term_calls/tests -v`. Pull requests run the rule and HTTP-fixture tests without touching the live journal. A main-branch installation registers future sealed calls and verifies authenticated FYERS daily history, complete prior-session minute history and Sheet access. Push checks do not generate retrospective calls. Workflow artifacts preserve raw requests/responses, candidates, reviews and source gaps for 90 days.
