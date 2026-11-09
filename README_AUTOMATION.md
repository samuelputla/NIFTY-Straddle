# Unattended paper collection and validation

This setup does not place broker orders. It preserves existing collectors, their own concurrency locks, 09:35 entry cutoff, prices and Sheet records.

## Independent cloud trigger

A Sites-linked cloud task uses the owner's connected GitHub tool, not a laptop/browser session. Each weekday at09:07 and16:07 Asia/Kolkata it reads this file and updates only `.automation/request.json` on `main` using its current blob SHA. It writes JSON containing `kind` (`start` before09:25 or `audit` after16:07), `date` (current IST YYYY-MM-DD), and `issued_at` (current timezone-aware ISO timestamp). Do not write secrets. Do not create pull requests for this tiny authorized trigger update. Never modify workflow files or collector code during scheduled runs.

The file's push starts `Automatic Session Control` independently of GitHub cron delivery. Its allowlisted controller rechecks GitHub runs and current Sheet dates. It never dispatches a queued/running/current-day workflow twice, never retries a failed/partial session automatically, and refuses morning dispatches after09:25. The existing collector09:35 cutoff remains intact. A `healthcheck` request reads workflow visibility only; it does not dispatch or touch market data. `disabled` is the inert installation value.

Morning targets: `straddle.yml`, `rolling-straddles.yml`, `daily-straddle-research.yml`; main only; test_mode=false/setup_only=false. Evening target: `eod-validation.yml`. GitHub's original schedules remain fallback triggers. A racing request is protected by existing workflow concurrency and the collectors' Sheet duplicate guards. Do not claim a204/click means tracking began: check the resulting controller report and new workflow/job IDs.

If the cloud task cannot access GitHub tools, it must report missing access and stop. It must not fall back to a laptop/browser or repeatedly dispatch. If it starts outside the morning window, it must not start paper positions. GitHub runner availability and the cloud task's own scheduling are still best effort. The first future cloud occurrence is not proven by successful installation or an author-session test.

## Daily Historical Validation

GitHub cron aims at16:07 IST (10:37 UTC). The independent16:07 cloud request supplies a separate trigger if no current-date validation run exists. This job has read-only repository permission and read-only Google Sheets credentials. It downloads each unique current contract's1-minute history once per audit, checks all nine studies, and saves report.json/report.md, Sheet source evidence and raw history as a30-day artifact. Original trade records and dashboard P&L are never overwritten. It does not use the expired-data endpoint or reset any quota ledger.

Checks include session completeness, duplicate cycles, expiry/DTE, ATM against recorded spot and entry-minute range, entry/reset/exit chronology, leg SL threshold consistency, missed minute-high crossings, full cycle candle coverage, arithmetic and assumedRs150/cycle costs. Saved delta entry/roll fields can be checked for strict change>0.35 and replacement neutrality; OHLC cannot independently prove the original continuous delta path. Historical/candle reconstructions remain identified. Quote ranges cannot prove second-level executable fills. Entry-minute SL ordering is explicitly limited.

Results: PASSED (available checks consistent, with listed limitations), REVIEW (record/rule/price discrepancy), DATA UNAVAILABLE (not enough source evidence). Authentication or structural/arithmetic errors fail the job so its normal GitHub failure mechanisms apply. Reports do not guarantee email delivery or broker execution. Market calendar is verified7Octâ€“31Dec2026 from NSEFAOP71777; unknown dates fail closed. Existing collectors also need their calendars maintained for2027. FYERS access may require renewal; no automatic credential bypass is attempted.

To inspect: Actions â†’ Daily Historical Validation â†’ latest run â†’ Job summary or daily-validation artifact. For one-off historical verification, audit_date accepts a past session date. It never starts positions. No manual trigger is required for the saved daily schedules.



## Additional research workflow health

Automatic Session Control now checks `short-strangle.yml` and `nifty-study.yml`
read-only whenever its existing cloud control request runs, and through its own
09:20 and 17:20 IST daily cron. Manual `check_new_workflows=true` runs only this
inspection, regardless of the default probe checkbox. It never starts or restarts
these two collectors. Their original schedules remain 09:10 and 16:30 IST.

Before preparation grace ends the report says NOT DUE, not failed. Short Strangle
is expected started by 09:20 and completed by 15:15. Nifty study is expected started
by 16:40 and completed by 17:05. Use each workflow's own market calendar; the
8 November equity special session is not treated as a normal F&O session.
Only schedule/manual executions count; equity push tests do not count as collection.
The report includes current-day run links and failed job/step names. Missing,
queued, failed, overdue, ambiguous or inaccessible executions fail the health job
so configured GitHub notifications can surface them. Notifications require the
user's GitHub settings; delivery is not guaranteed. SUCCESS means job execution,
not independent validation of forecast quality, prices or published Sheet rows.

Inspect the run summary and workflow-health.json/md artifacts. GitHub cron is still
best effort; these checks are not an independent real-time scheduler. Existing
09:07/16:07 cloud controls also include status checks, but a separate post-16:30
cloud wake-up is not configured by this change. Failed or partial runs need review,
not blind reruns. No core strategy or broker permissions were changed.

