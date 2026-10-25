# Competition card format

New cards, explicit owner resends, and in-place updates use the same renderer in `TelegramClient.send_competition`.

- Keep title/status, reward/deadline/fee, effort estimate, known submission rules, and source links.
- Date-only deadlines show the date and `24:00`; omit the explanatory default-timezone/end-of-day parenthesis. Unknown fees show `未確認` once.
- Do not repeat the six-hour/AI/tool-budget policy targets or the standard waiting/tool/submission/award disclaimer on each card. The assessment still retains those rules and provenance.
- Group planning and generation into production time, review and submission into checking/submission time, and show positive additional finalist time when available. Keep the flow on one line and never display free-form model plans as facts.
- Omit the duplicate investment summary, raw AI-rule excerpt, and long unknown-field list. Pending cards show at most two distinct priority blockers once; rejected cards show at most three reasons. Keep source links and independently evidenced mandatory conditions, including human-only work and licensing restrictions.
- Preserve HTML escaping, Unicode limits, uncertain estimates, missing fees, and pending/rejected status. Presentation changes must not promote a pending assessment to eligible or change automatic-delivery policy.

`tests/test_competition_card_concision.py` captures the reported mobile-card regression for both send and edit paths, checks that all removed boilerplate remains absent, enforces a compact sample, and verifies that rendering does not mutate the assessment.
