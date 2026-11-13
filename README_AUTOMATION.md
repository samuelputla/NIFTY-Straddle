# Paper workflow scheduling and fallback

GitHub cron is best effort, not an exact-time service. On 12 November the 08:55 IST Fixed and Rolling schedules were created around 17:00 IST. Manual morning runs supplied the actual observations. A successful skipped workflow is not evidence of a collected session.

## Independent cloud wake-up

The owner-authorized cloud scheduled task updates only `.automation/cloud-wakeup.json` on main with current IST `date` and timezone-aware `issued_at`, using the existing blob SHA. Never store credentials in this file. Its push starts `Paper Session Fallback` (`session-control.yml`). This request is accepted for 15 minutes only. A local Codex reminder is not an independent cloud scheduler.

The controller reads Actions and summary dates before dispatching due workflows. Active runs, current-day completed or failed runs, and existing option summary rows prevent blind restarts. Failed or partial collections require review. Morning collectors are never dispatched after their cutoff. Short Term Calls may run again after 14 minutes; its workflow lock serializes writers. The close check is distinguished from morning Strangle collection by its run title.

| Workflow | Native target IST | Fallback window IST |
| --- | --- | --- |
| Fixed Entry | 08:55 weekdays | 08:55 to before 09:25 |
| Time and Delta | 08:55 weekdays | 08:55 to before 09:25 |
| Short Strangle collect | 09:10 weekdays | 09:10 to before 09:25 |
| ABC paper | 08:55 weekdays | 08:55 to before 09:10 |
| Short Strangle verify | 15:05 weekdays | 15:07 to before 18:00 |
| Nifty Study | 16:30 daily | 16:30 to before 23:30 normal weekdays |
| Short Term Calls | 08:50, 09:05; every 15 minutes 09:20–15:35; 16:05, 18:05 weekdays | 08:50 to before 18:30, no more than once per 14 minutes |

Fallback GitHub crons are additional attempts, not an independent timing guarantee. The independent cloud task must be saved, connected to GitHub with write access, and tested separately. A dispatch acceptance is not a completed collection. Inspect `session-control-report.json`, target jobs and the Sheet. Future scheduling remains unverified until its first occurrence.

## Audit findings and data limits

Collectors are paper-only. No broker order endpoint is authorized. The option observer captures entry Greeks/depth and 09:30–15:00 highs, with actual timing and availability. Missing historical entry Greeks cannot be recreated from a current API quote. Historical margin has no as-of calculator; current verification amounts must not become historical entry margins.

Retired Automatic Session Control / Daily Historical Validation workflows are not installed. Old `automation_dispatch.py` / `workflow_health.py` are historical helpers, not proof of an active schedule. Calendar checks fail closed outside their verified 2026 interval and need updating before 2027.

