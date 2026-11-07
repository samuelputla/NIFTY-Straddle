# Upstream review

Reviewed 7 November 2026: https://github.com/Jakeschincariol/trader-skill

Inspected README.md, trader-screener/SKILL.md and screen.py, trader-analyst/SKILL.md, trader-news/SKILL.md and trader-risk/SKILL.md. This was a targeted review, not an audit of all eleven modules, dependencies or tests. No upstream code was executed or copied.

Useful design ideas: explainable rules and scores; machine-readable handoffs; missing-data reasons; checking primary filings behind headlines; distinguishing filed and derived numbers; separating screening from execution. Adapted conceptually into this original NIFTY research protocol.

Limitations for this study:
- US SEC/13F/Congress, NYSE calendar, US tax and Alpaca workflows are not NSE/FYERS integrations.
- The screener evaluates supplied metrics; it does not establish next-session predictive accuracy. Its percentile score is not a win probability.
- screen.py accepts missing='skip' and renormalizes ranking over available metrics. For comparable research rankings, this skill instead requires explicit coverage and separately versioned reduced-feature variants.
- The generic screener does not itself enforce immutable pre-session forecasts, point-in-time features, full-universe outcomes or chronological forward evaluation.
- Upstream examples and popularity do not substantiate trading performance. The inspected material supplies no NIFTY next-day prediction validation.

Source pointers:
- https://github.com/Jakeschincariol/trader-skill/blob/main/trader-screener/screen.py (blob 3101d7e57bce87c43387e64c703f916f18b2215e)
- https://github.com/Jakeschincariol/trader-skill/blob/main/trader-news/SKILL.md
- https://github.com/Jakeschincariol/trader-skill/blob/main/trader-analyst/SKILL.md
- https://github.com/Jakeschincariol/trader-skill/blob/main/trader-risk/SKILL.md
