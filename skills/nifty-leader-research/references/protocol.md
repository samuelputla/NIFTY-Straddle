# Research protocol

## Freeze before evaluating

Create a versioned rules specification with universe date, decision cutoff, target session, shortlist size K, leader count L, feature windows, filters, ranking weights, ties, missing-data policy, benchmarks and execution assumptions. Proposed initial convention: K=5 and L=5, subject to recording before the first prospective run. A full 50-stock universe makes random expected precision L/50 (10% when L=5); constrained universes require their own null baseline.

Required features cannot be silently skipped or their weights redistributed. Exclude affected stocks with an explicit reason and report coverage. Test a reduced-feature specification as a separately frozen variant. Do not optimize thresholds on holdout or future results. Do not equate high RSI, a breakout or news sentiment with an established predictive edge.

## Candidate feature definitions

Use only completed data available at the cutoff. Specify price adjustments and consistent units.

- Prior resistance/support: highest high/lowest low over N preceding completed sessions, excluding the session being assessed for a breakout. Report distance as a percentage.
- Consolidation: (rolling highest high - rolling lowest low) / latest close over a fixed window. A threshold is a hypothesis to test.
- Volume ratio: completed session volume / mean volume of the preceding 20 sessions, excluding the numerator session. Intraday relative volume requires the same elapsed-time historical denominator.
- Trend: close relative to SMA20/SMA50, plus explicitly defined slope or return windows.
- RSI14: Wilder smoothing; MACD: EMA12 minus EMA26 with EMA9 signal. Record seeding/warm-up conventions; do not mix library defaults silently.
- Relative strength: stock simple return minus benchmark simple return over identical 5/20-session windows. Use Nifty and a documented sector index or fixed sector basket. Avoid changing basket membership retrospectively.
- Catalysts: issuer, category, source URL, event time, publication time, first observed time, revision time and availability at cutoff. Missing original publication time makes historical eligibility uncertain. Revised fundamentals require point-in-time versions; today's restated data cannot stand in for what was known then.

## Return labels and evaluation

For target session t, use consistent official daily prices when available:

- Close-to-close: close[t] / close[t-1] - 1.
- Opening gap: open[t] / close[t-1] - 1.
- Open-to-close: close[t] / open[t] - 1.
- Multiplicative reconciliation: (1 + gap) * (1 + open-to-close) - 1 = close-to-close.

Rank close-to-close leaders and open-to-close leaders independently. Specify symbol tie-breaking before evaluation. Report precision@K, recall of top L, lift versus random selection, mean/median candidate return and excess return versus Nifty. Compare identical dates and coverage with prior-day winners, simple past-20-session momentum and a defined sector-strength-only rule. Include all dates and rules attempted, not only successful examples.

Use chronological train/validation/holdout splits or walk-forward testing. Tune on training only; purge overlapping outcome horizons where relevant. Aggregate uncertainty by session because stocks on a day are correlated. Report confidence intervals and regime breakdowns without claiming a fixed session count guarantees validity.

Prediction ranking and executable trading returns are separate outputs. Trading tests must define entry time/price, spread, slippage, brokerage/taxes, exits and capital constraints. Overnight gaps require a prior-session entry assumption. Candle highs/lows cannot prove executable fills or stop/target ordering. Record adverse moves and losses. Never turn daily top-gainer identification into a claim that its full return was capturable.

## Minimum stored records

- Input manifest: source, retrieval timestamp, market as-of, session, universe version, adjustment policy, symbol mapping, row counts, missing symbols, SHA256 for raw files.
- Feature rows: session, symbol, feature version, numeric values/units, source availability timestamps, missing reasons, catalyst evidence.
- Forecast: forecast ID, created_at, cutoff, target_session, rule hash/version, input hashes, ranked candidates, score components, exclusions, research status. Preserve original bytes; later annotations reference the ID.
- Outcome: forecast ID, actual session, all-member returns/ranks, candidate hits, benchmarks, costs if modeled, coverage issues and evaluation timestamp.

Insufficient inputs produce a data-quality report and no fabricated shortlist. A forecast saved after its cutoff is retrospective even if a manually entered timestamp claims otherwise; use observable creation evidence.
