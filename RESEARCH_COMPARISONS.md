# Isolated forward comparisons - comparison-v1

Start: 2 November 2026. Nine baseline strategies, nine existing independent SL levels, one change per comparison. No live orders and no changes to entry, exits, stops, expiry selection, time/delta roll rules or baseline accounting. Collector additions are bounded, nonblocking observation queues only. No new live broker requests or subscriptions. A failed observer marks research unavailable; it must never stop the baseline.

## Frozen alternatives

1. EXIT_1330 and EXIT_1430: keep all prior baseline cycles and independent stops, close remaining shorts on the first saved quote at/after the deadline within 10 seconds; no later entries.
2. TARGET_40 and TARGET_50: gross cycle profit (realized stopped legs plus marked surviving shorts) reaches 40% or 50% of that cycle's initial CE+PE credit. Stops have priority on the same observation. Use both current marks only when fresh within 10 seconds. Require complete sampled paths without >10-second gaps. After a target, Fixed Entry and Delta Based remain flat; Time Based may enter at its next scheduled baseline reset. No borrowing of post-target Delta rolls from the baseline.
3. WINGS_500 and WINGS_1000: same baseline short legs and roll schedule; buy equal-quantity same-expiry CE at ATM+width and PE at ATM-width at each baseline cycle. Close wings when that cycle closes. Use the last pre-event chain snapshot no more than 30 seconds old, entry ask and exit bid. These are INDICATIVE results: displayed size/execution is not established. Missing/zero/crossed quotes are unavailable. Initial static expiry loss is width*65 minus net entry credit; it is not broker margin, a daily risk limit, or the total rolled risk.
4. FILTER_VIX: take the baseline only if a VIX observation actually received before entry (max 30 seconds old) is <=1.2 times the mean of the prior 20 distinct session closes. Never use an after-entry metadata result as a pre-entry gate.
5. FILTER_GAP: take the baseline only if absolute opening gap from previous close is <=0.75%. Equal-boundary days trade. No gate combines these filters in v1.
6. FILTER_EVENT: skip scheduled RBI MPC meeting days only. Scope and dates are sourced from RBI's 23 March 2026 schedule: https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62422. Covered period is April 2026-March 2027; other event types are not covered. Outside coverage is unavailable, not a non-event day.

The 25% SL is the predeclared primary analysis level within each strategy; other SLs remain secondary comparisons. No automatic winner or live promotion. These thresholds are research hypotheses, not optimized/proven settings.

## Regimes and holdout

Complete 09:30-14:59 NIFTY one-minute candles label the realized session. Efficiency = absolute open-to-final-close displacement / sum of absolute consecutive one-minute price changes. >=0.35: trending up/down; <=0.20: range-bound; between: mixed. Missing any of the 330 minutes: unknown. Gap direction is separate. End-of-day regime never gates entry.

First 60 chronologically complete common baseline sessions form calibration; next 30 form the frozen holdout; later dates are post-holdout. Sixty is a review checkpoint, not proof of reliability. Existing assigned cohort/phase values are stable on retry. All nine baseline summaries must reconcile to their complete cycle logs before the date can advance the cohort. Version changes require a new cohort, not retroactive editing. Report all attempted comparisons and missing coverage; do not select an apparent historical winner and present the same data as holdout evidence.

## Accounting and pairing

Use existing threshold-paper short fills and INR150 per two-leg cycle. Four-leg hedge cost assumption is INR300/cycle; actual taxes, brokerage and fill costs remain unverified. Doubled-cost net subtracts one more full assumed cost for every actual comparison cycle. Never sum SL alternatives as simultaneous executions. A skipped filter day earns zero with zero comparison fees and stays in the same-date paired sample. Missing data is blank, never zero. Returns on actual broker margin remain unavailable.

## Storage, automation and permissions

- Only Research Comparisons and Comparison Market Regimes tabs are written. Core nine tabs/logs are read only by the comparison runner.
- Existing fixed/rolling workflows retain the same entry/exit processes. Optional observer journals reuse current ticks and full chain responses, with a 200MB compressed cap and a bounded queue.
- The existing 16:07 IST validation workflow runs a separate comparison job after its read-only audit, including if that audit reports a failure. An explicit past-date audit does not run the comparison publisher. No additional daily manual workflow is required. Before the start date only schemas/empty readiness state exist.
- GitHub action artifacts preserve capture journals and comparison reports for 90 days, subject to repository retention policy. Download/archive them for longer storage. Partial or test journals are rejected.
- Post-session context uses three normal FYERS history requests (NIFTY minute, NIFTY daily, VIX daily), spaced apart. No expired-history endpoints or history quota resets. Authentication/data failures yield unavailable inputs.
- Month snapshots are compacted without dropping rows and signed with the already-configured Sheet service account. Public dashboard writes require a valid RSA signature and a fresh timestamp. Private keys never leave backend configuration or enter the browser.
- The verified NSE session calendar still needs the official 2027 update when published. Do not invent holidays to extend collection.

No historical results are invented. All paper improvements require future paired, cost-aware, out-of-sample assessment before any live trading decision.

