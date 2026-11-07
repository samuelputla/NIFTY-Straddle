# Nifty study

An isolated equity research workflow beside the existing straddle studies. Scheduled at 18:30 IST daily; GitHub scheduling is best effort. Uses the verified 2026 NSE equity calendar, including the 8 November Muhurat session. It fails closed beyond 2026 until the calendar is maintained. No broker orders or strategy modifications.

## First implementation

Downloads today's official 50-member constituent snapshot, about 300 calendar days of FYERS daily history for stocks/Nifty, and today's 15-minute stock candles. Requires matching latest daily sessions and adequate warm-up/volume. Saves raw responses and hashes in 90-day workflow artifacts and writes separate Study tabs in the existing spreadsheet.

Computes daily returns, gaps, open-to-close moves, SMA20/50, Wilder RSI/ATR/ADX14, EMA12/26/9 MACD, stochastic14, prior 20-session support/resistance, breakouts, prior completed weekly return, Nifty relative strength, industry peer proxies, intraday trailing returns, approximate VWAP/profile POC and an explicit experimental order-block zone. Profile volume is assigned to typical-price bins; it is not true volume-at-price. Intraday features are descriptive and do not silently substitute for required daily features.

Frozen exploratory `price-volume-v1` ranks all 50 on equal-coverage percentile features: Nifty RS20 (weight 2), stock momentum20, RVOL20, distance from SMA20 and industry-peer momentum (weight 1 each). Top five become paper candidates. This is an initial hypothesis, not a learned/validated predictor. No probability claims. Single-member industries have a neutral sector feature with an explicit warning.

## Findings and learning

Study Observations retains every member, not just winners. Study Forecasts retains all 50 scores, reasons, original ranks, forecast timestamp and input hash. Study Reviews scores prior frozen forecasts into hits, false positives, missed leaders and controls, separating gaps and intraday returns. The daily artifact also compares precision@5 with random selection, prior winners, momentum and sector-only rankings. Calendar special sessions are labeled separately; do not compare their volumes naively with normal sessions.

Study Changes logs miss-review proposals; it never promotes a new rule or edits the skill automatically. Proposed explanations need evidence across controls and future sessions. This chat remains the place to review those findings and request changes.

## Fundamentals and news coverage

The NSE RSS reader discovers candidate announcements by issuer, deduplicates them and writes UNVERIFIED leads. It does not read PDFs or assert headline causality. A reviewer adds verified filings/news/fundamental metrics to Study Evidence with publication/observation timestamps and source links. Those observations appear in the report, but are not secretly folded into v1 ranking. Automated point-in-time financial extraction, official sector-index mapping, true trade-level volume profiles and a full multitimeframe/order-flow study are not implemented. Missing coverage is disclosed in every run. No model/API key for autonomous language-model analysis is assumed.

## Reliability

Requires existing FYERS_ACCESS_TOKEN and GOOGLE_SERVICE_ACCOUNT_JSON secrets with read-only market access and write access to the existing Sheet. No secrets are stored in this repository or artifacts. A push runs a connection check only; it cannot issue a forecast. Scheduled/manual normal runs operate on today's session after 16:15 IST and refuse forecasts created after the next open. Initial constituent snapshots cannot support old-universe backtests. Provider daily-close adjustment status is unverified; corporate actions require review before interpreting large changes.

Study table publication is one atomic append request with a unique daily run key, re-read after ambiguous errors. Workflow concurrency prevents normal duplicate runs. Original forecasts are never overwritten. Users editing Sheet timestamps could invalidate provenance; retain GitHub artifacts/run times as independent evidence. Do not treat manual Sheet changes as immutable externally audited records.

Run locally: `python -m unittest discover -s nifty_study/tests -v`. In a securely authenticated environment: `python -m nifty_study.run --connection-check`, then `python -m nifty_study.run` after session finalization. Production endpoints are fixed; simulation endpoints are injected only by tests.
