# Monthly Expiry — isolated NIFTY paper straddle

Select the nearest monthly NIFTY expiry, including that contract on its actual expiry date. Resolve monthly dates from the current FYERS NIFTY futures contract master; require matching option-chain expiry metadata and exact ATM CE/PE symbols in the option master. Fail without entry on disagreement. Never manufacture symbols or silently substitute a weekly expiry.

At 09:30 IST, sell the nearest 50-point ATM CE and PE on paper. Entry cutoff remains 09:35. Independent 10/15/20/25/30/35/40/45/50% stops close only the stopped leg at its threshold; retain the other leg's original stop. Exit survivors at 15:00. No re-entry, rolling, trailing, hedges or live order routes. Preserve the existing study assumptions: 65 units per leg and ₹150 combined session charges, ₹250,000 dashboard capital.

Own workflow: monthly-expiry-straddle.yml; own process/state, Monthly Expiry summary, Monthly Expiry Logs, /api/monthly and monthly-expiry-summary.json. Scheduled startup matches existing strategies; GitHub schedule delivery remains best effort. Do not manually start late normal sessions or duplicate an existing session.

Current Week Expiry selects the nearest listed expiry (including today). Next Week Expiry selects the second distinct listed expiry. These labels do not force calendar-week arithmetic; holiday-adjusted listed dates govern. Monthly and Current Week may select the same contract during monthly-expiry week; keep results separate.

DTE is calendar days from the session date to actual expiry, including weekends/holidays; expiry day = 0. It is appended to summaries (CE) and logs (AE), without shifting prior columns. Past DTE is derived from recorded date/expiry, not from current contracts. No monthly history is fabricated.
