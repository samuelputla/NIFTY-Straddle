---
name: nifty-leader-research
description: Research conditions preceding NIFTY 50 daily leaders, build timestamped next-session paper shortlists, and score them against all constituents and simple benchmarks. Use for the Top Gainers study, CSV audits, FYERS research collection, forward evaluation, and Opening Momentum missed-leader reviews.
---

# NIFTY leader research

For Indian-market adaptation of trader-skill modules, source selection and implementation boundaries, read [NIFTY adaptation](references/nifty-adaptation.md). Apply its research modules when collecting, screening or reviewing catalysts; portfolio and broker modules remain conditional on a separate request.

Find whether information available before a session helps shortlist that session's leaders. No validated predictive edge currently exists. Read [research protocol](references/protocol.md) for feature definitions, evaluation and output records; read [source review](references/source-review.md) when discussing the upstream trader-skill repository.

## Working boundaries

- Research and paper calls are authorized; broker execution, publishing calls, and new recurring schedules require their own user instruction. Do not start options collectors to obtain equity research data.
- Verify authenticated read-only FYERS access before describing it as working. Existing GitHub code or secret references are not authentication evidence. Never retrieve, print, persist or commit credentials. Use the service's supported authenticated connection.
- The available screener_stocks.csv has 40 stocks, no session timestamp, and zero volume for every row. Its price arithmetic reconciles, but it cannot establish complete NIFTY 50 rankings or volume signals. Ask for missing dates; never infer market timestamps from file modification times.
- The lost zerodha_source_2026-11-05.csv and reported 39-gainer baseline are unverified until reproduced. Preserve that distinction in reports.
- The 15-minute breakout/retest/confirmation entry experiment is separate. It cannot be inserted into an evening forecast using next-session observations.

## Daily study

Use the [daily review loop](references/daily-review.md) for the user's post-session study, next-session prediction list, and review of missed leaders and failed candidates. Broad analysis is authorized; unsupported techniques must be marked unavailable rather than invented.

1. Establish the session calendar, timezone Asia/Kolkata, decision cutoff, target session and historically valid 50-member universe. Keep effective-dated constituent and sector mappings. Verify all expected symbols, duplicates, dates, OHLC relationships, previous close, corporate actions, volumes and source timestamps. Retain raw inputs unchanged with hashes and provenance.
2. Collect sufficient daily OHLCV history plus Nifty and sector benchmark histories. Quotes supply snapshots; history supplies completed candles. Distinguish last traded price from official session close. Missing, stale or placeholder volume is unavailable, not zero participation. Disclose secondary-source fallbacks and adjustment differences.
3. Calculate lagged price, volume and relative-strength features identically for every member, including losers. Use explicitly defined windows, formulas and warm-up periods. Keep financial periods and publication timestamps distinct. Verify material news against exchange/company filings; a headline is only a lead.
4. Explore leaders against non-leaders over many sessions. Record each hypothesis and attempted variant. Do not claim causality from a winning-stock narrative. Separate exploratory results from chronological holdout and forward tests.
5. Before the target session, freeze the rule version, eligible inputs, cutoff, candidate list, scores, exclusions and creation timestamp in an append-only research record. Hash the inputs and rule specification. Late records are retrospective and cannot enter forward statistics. Scores are not calibrated probabilities.
6. After the target session, join outcomes to the original frozen record and evaluate all forecasts, including failures and empty shortlists. Never overwrite a forecast with revised selections. Report coverage gaps and sample size with results.

For Opening Momentum, follow the [opening review](references/daily-review.md#opening-momentum-review) to explain missed leaders and paper-trade outcomes using the frozen 09:45 IST inputs.

## Reporting

Lead with what is verified, what is unavailable, and whether a shortlist is prospective or retrospective. Show each candidate's feature values, thresholds, evidence links, risk/counterevidence and missing inputs. Give confidence percentages only for specifically justified judgments, never fabricated prediction probabilities. Do not present an untested rule as a validated call.

Saving this skill does not implement a collector, authenticate FYERS, schedule jobs or generate a forecast. State the actual operational status.
