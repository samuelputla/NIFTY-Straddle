# Measurement upgrade - baseline rules unchanged

Effective for the next fresh collector session after merge; no restart and no historical Greek invention.

## Delta evidence
`Delta Measurements` adds one stable row per session/expiry/SL/cycle: reference, timestamped original CE and PE deltas (long-option convention), unscaled short-pair delta, sampled min/max and maximum absolute change, first change strictly greater than 0.35, maximum interval between valid samples, latest observed close delta and whether a subsequent cycle exists. Stopped contracts stay in the signal. Sampling reuses existing option-chain responses (roughly 15 seconds per expiry in normal operation); no extra FYERS requests are added. It is sampled evidence, not a guarantee that no brief crossing happened between samples. `Last Sample Time` is essential when interpreting `Close Delta`.

Full samples are `delta_observations.jsonl` in the rolling workflow artifact (30-day retention). Save/download these artifacts for longer retention. The trade logs retain the same columns and P&L definitions.

## Execution evidence
`Execution Measurements` stores each stop's threshold, crossing timestamp/LTP, assumed paper fill, and their signed difference in points and INR (65 units). The observed LTP is NOT an executable fill. The existing lightweight feed does not establish synchronized bid/ask; these fields stay blank and are explicitly unavailable. No arbitrary slippage is silently added to the baseline.

Fixed-entry collector evidence is also saved as a per-job artifact. Rolling state retains observed stops. Optional evidence IO is outside the quote lock and failures do not change strategy decisions. Retrying evidence saves checks stable IDs.

## Dashboard
The Master Overview adds DTE bands, doubled-recorded-cost net, profit factor, nonannualized daily mean/sample-volatility and mean/downside-RMS ratios. The doubled-cost result is recorded net minus one additional recorded cost for every actual cycle. SL alternatives are never summed as concurrent trades. Existing totals remain untouched. Zero denominators and missing data stay unavailable. Shared-date mode remains the default. Drawdown uses chronological daily closes, not intraday mark-to-market. Capital return uses assumed INR250000; broker-margin return is unavailable until point-in-time margin is recorded.

## Separate next experiment (not activated)
Survivor-to-entry challenger: after the first leg stops, move only the surviving leg's stop to its own original entry premium. Do not reset the stopped leg, re-enter, or mix results with baseline. Collect the same incoming quotes in a separate shadow account/state; compare on identical session/expiry/SL dates with independent actual-cycle costs. Freeze this definition before sampling. A same-tick crossing is an observed paper event, not a guaranteed fill. This document defines a future isolated experiment; it creates no positions, workflow or performance claims.

Do not change VIX/gap filters, entry/exit times, hedges, stops or delta thresholds together. No minimum session count proves reliability; keep sample size and future holdout results visible.

