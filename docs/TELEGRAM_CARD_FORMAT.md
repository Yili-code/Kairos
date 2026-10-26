# Competition card format

New cards, explicit owner resends, and in-place updates use the same renderer in `TelegramClient.send_competition`.

- Keep title/status, reward/deadline/fee, effort estimate, known submission rules, and source links.
- Date-only deadlines show the date and `24:00`; omit the explanatory default-timezone/end-of-day parenthesis. Unknown fees show `未確認` once.
- Do not repeat the six-hour/AI/tool-budget policy targets or the standard waiting/tool/submission/award disclaimer on each card. The assessment still retains those rules and provenance.
- Group planning and generation into production time, review and submission into checking/submission time, and show positive additional finalist time when available. Keep the flow on one line and never display free-form model plans as facts.
- Omit the duplicate investment summary, raw AI-rule excerpt, and long unknown-field list. Pending cards show at most two distinct priority blockers once; rejected cards show at most three reasons. Keep source links and independently evidenced mandatory conditions, including human-only work and licensing restrictions.
- Preserve HTML escaping, Unicode limits, uncertain estimates, missing fees, and pending/rejected status. Presentation changes must not promote a pending assessment to eligible or change automatic-delivery policy.
- Keep the pending status to one phrase (`待確認`). Display recommendation separately: high for eligible, free, no-attendance entries within the assessed effort/tool limits; medium for other fully assessed eligible entries; low when current estimates exceed the six-hour/tool-cost limit or fall below the AI-production threshold; ungraded when key facts/estimates remain unresolved; not recommended for rejected entries. These preference tiers are not award probabilities and never change qualification or delivery policy.

`tests/test_competition_card_concision.py` captures the reported mobile-card regression for both send and edit paths, checks that all removed boilerplate remains absent, enforces a compact sample, and verifies that rendering does not mutate the assessment.

## Information gate

An already-delivered record is historical evidence, not a recommendation or permission to resend it. Before any real competition card send or edit, require sourced cash-prize information, a sourced future deadline, sourced deliverables and AI rules, and usable total-hours/AI-share/tool-cost estimates. Missing data stays in background screening; `/competition` returns a short missing-information status instead of an empty opportunity card. Manual resends use the same final Telegram gate. `competition_payload` is a pure layout preview and must not be used to bypass delivery validation.

Automatic competition notifications additionally require `decision=eligible`. A pending card with useful information can only be sent on an explicit owner request. All pending assessments stay in bounded screening recovery with cooldowns; failed or interrupted automatic claims consume the existing three-attempt budget.

A failed refresh retains the previous assessment and message receipt. It cannot replace the useful card with missing fields, counts as unresolved, waits four hours before another attempt, and pauses after three incomplete attempts. Explicitly queued incomplete edits obey the same bounded deferral. The old assessment is not falsely marked freshly verified. Owner decisions and newer versions remain protected by the existing transactional guard.

## AI permission provenance

A live-model replay selected a PayPal clause requiring an application to integrate an AI tool as evidence of broad AI artifact-creation permission. The evaluator now requires explicit creation/generation permission or an explicitly permitted AI-generated/assisted entry. A product's AI topic, required API, or model integration alone stays unknown. Positive component-specific permissions remain usable, while a sourced prohibition cannot be upgraded by an erroneous model enum. This check does not infer permission from silence, override other qualification gates, or establish a probability of winning.
