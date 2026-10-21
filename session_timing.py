"""Startup timing evidence only; no broker, Sheet or workflow API calls."""
import json
import os
import sys
from datetime import datetime, time
from zoneinfo import ZoneInfo

now = datetime.now(ZoneInfo('Asia/Kolkata'))
target = datetime.combine(now.date(), time(9, 30), tzinfo=now.tzinfo)
record = {
    'stage': sys.argv[1] if len(sys.argv) > 1 else 'startup',
    'actual_ist': now.isoformat(),
    'entry_target_ist': target.isoformat(),
    'seconds_until_entry': round((target - now).total_seconds(), 1),
    'event': os.getenv('GITHUB_EVENT_NAME', 'local'),
    'run_id': os.getenv('GITHUB_RUN_ID', ''),
}
print(json.dumps(record), flush=True)
summary = os.getenv('GITHUB_STEP_SUMMARY')
if summary:
    with open(summary, 'a', encoding='utf-8') as f:
        f.write(f"\n### {record['stage']}\nActual IST: {now.isoformat()}\n\n"
                f"Seconds until 09:30: {record['seconds_until_entry']}\n")
