# Daily leader study and learning loop

## Session sequence

After session D is finalized, evaluate the forecast previously frozen for D. Study D's leaders using the full universe as controls. Distinguish information observable by the preceding forecast cutoff from evidence that arose during D. Build a new, timestamped paper shortlist for the next verified trading session D+1 using only information available by the new cutoff. Score that exact forecast after D+1; never replace its entries retrospectively.

Default study remains NIFTY 50. Examples of named stocks do not establish constituent membership. Verify effective-dated membership, renames and listed entities. Record a requested broader NSE watchlist as a separate universe and evaluate it separately; a winner outside the frozen universe is a scope exclusion, not a model miss.

## Broad evidence review

For each leader, shortlisted candidate, missed leader and matched non-leader, use the same feature definitions and data availability checks:

- Fundamentals: latest publicly available earnings, sales/profit growth, margins, leverage, valuation, guidance and exceptional items. Record publication dates and sector-specific relevance; slow financial data alone cannot establish the cause of one day's move.
- Catalysts and context: exchange/company announcements, earnings timing, reputable reported developments, sector and index moves, macro events and corporate actions. Keep observed facts, plausible mechanisms and unknown causes separate. No news found is not proof there was no catalyst.
- Price structure: weekly/daily trend and prior levels, consolidation, volatility compression, breakout/rejection, opening gap and whether gains persisted or faded. Use completed weekly bars at the forecast cutoff; partial bars must be explicitly labeled.
- Timeframes: weekly/daily for context; completed 60-minute/15-minute bars for the sequence when history is available. Record exchange-aligned resampling boundaries and partial last bars. Select additional timeframes for a specific hypothesis, not to search until a favorable chart appears.
- Indicators/oscillators: moving averages, RSI, MACD, ATR and optionally ADX/stochastic with versioned windows and smoothing. Closely related indicators are not independent confirmations. Test incremental information using ablations rather than adding every indicator to a score.
- Participation: relative volume, turnover, breakout volume, same-time intraday volume and session VWAP when data supports it. Full-day volume observed during D can explain D retrospectively but could not be an input to the earlier forecast for D.
- Volume profile: record session/anchored lookback, bin size, value-area fraction, POC/VAH/VAL algorithm, ties and source resolution. True volume-at-price requires trade-level or provider profile data. Allocating candle volume across prices is an approximation and must be labeled; daily OHLCV cannot recover a real profile.
- Order blocks and liquidity zones: treat them as explicit price-pattern hypotheses, not verified institutional orders. Freeze the algorithm (candle selection, displacement threshold, break of structure, confirmation time, mitigation and invalidation). A zone becomes available only when all confirming bars have completed. Do not draw a zone with future candles and backdate it.
- Order flow/positioning: use authenticated depth/trade/OI observations only if actually available and relevant. Equity bid/ask snapshots are not executed flow; futures OI requires correct contract/roll handling. Avoid claims of accumulation, stop hunting or short covering without supporting evidence.

Maintain an evidence matrix: feature, value, timeframe, known_at, source, quality, supporting evidence and counterevidence. Mark missing analyses unavailable. Broad coverage means considering relevant explanations, not claiming all possible causes are knowable.

## Forecast and failure review

Freeze candidate ranks, rule version, feature values, reasons, counterarguments, missing data and falsifiable expectations. Save all eligible scores and excluded symbols, so the next day's review can explain why an actual leader was below the cutoff. Optional scenario notes (continuation, gap/fade, sector rotation, new catalyst) are conditional hypotheses; they cannot retroactively change the forecast list.

Classify outcomes:

1. Selected and became a leader: hit. Check whether the expected setup actually occurred or the hit arose from unrelated new information.
2. Selected but not a leader: false positive. Distinguish a profitable non-leader from a loss, and relative ranking failure from absolute direction failure.
3. Eligible, not selected, became a leader: false negative. Inspect original scores, filters, missingness and publication times before proposing an omitted feature.
4. Eligible, not selected, not a leader: control. Include these to test whether the supposedly explanatory pattern is common everywhere.

For an ADANIPORTS false positive and CIPLA missed leader, compare their frozen pre-session features, score contributions, exclusions, prior resistance, sector strength and known catalysts, then separately inspect the actual session path and any new disclosures. Classify the failure as data error, universe error, feature omission, scoring/rank cutoff, regime dependence, new post-cutoff information or unresolved variation. Do not assume every miss was predictable.

## Skill and model changes

Log every miss and proposed explanation. Correct demonstrated data/implementation errors promptly, preserving originals and labelling recomputed results. A new predictive pattern requires a precise hypothesis, measurable feature and comparison against non-leaders across multiple sessions. Test incremental value chronologically, retaining an untouched holdout and the record of attempted variants.

Keep the current baseline frozen while a revised challenger runs prospectively in parallel. Promote a rule only after predeclared comparison criteria support it; report uncertainty and sample size. Updating the skill can document evidence gaps immediately, but must not present each newly observed pattern as a proven filter. Retain unsuccessful hypotheses to prevent repeated rediscovery and selective reporting.

## Daily report

Deliver: data coverage and session/cutoff; actual leaders and gap/intraday decomposition; evidence-backed explanations with uncertainty; original forecast versus outcomes; false-positive/false-negative/control comparisons; next-session timestamped paper shortlist; and a change log distinguishing observations, proposed tests and accepted corrections. If data is insufficient, issue the coverage report instead of manufacturing a forecast.

## Opening Momentum review

1. Use the frozen 09:45 IST features for all 50 stocks, the five picks and the closing top five. Record opening rank, closing rank, score gap to fifth place, tie-breaks, and each feature's score contribution. Compare missed leaders with selected names and nearby non-leaders. Mark older records without full frozen inputs as incomplete.
2. Compare the completed prior daily trend, RSI, MACD, ADX, stochastic, ATR, support and resistance with opening price action, same-time relative volume, sector strength and candle-based VWAP. Inspect the post-cutoff move, including when a breakout became observable.
3. Read timestamped NSE/company announcements and quarterly financials. Record the reporting period, release timestamp, link and relevant figures. Check sector news and reputable reporting when warranted. Label data gaps and keep releases through 09:45 distinct from later releases.
4. Explain separately why the ranker excluded the name and why the trade failed to capture a move. Inspect simulated entry, stop, target, timed exit, costs and post-entry path for selected names. For missed names, treat any hypothetical entry and return as retrospective. Record any unverified catalyst as a hypothesis.
5. Update the review procedure when evidence reveals a recurring gap. Log a measurable proposed feature and matched controls. Test alongside the frozen score across at least 30 eligible paired sessions before considering a change. Review the Opening Momentum Review tab and GitHub artifacts for evidence and coverage.
