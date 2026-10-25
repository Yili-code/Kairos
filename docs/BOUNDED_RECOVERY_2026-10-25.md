# Bounded screening recovery and safe card refreshes

## Confirmed defects

- Scheduled card refreshes saved the complete candidate after provider I/O. An owner skip or newer assessment could be overwritten, including within the same clock timestamp.
- Failed screening retained a cooldown but no finite attempt budget. Repeated insufficient evidence or repeated interruptions could consume automatic processing capacity indefinitely.

## Repairs

- Refreshes work on a copy, compare the complete original candidate snapshot inside a Firestore transaction, and write only assessment fields. A stale refresh is discarded before editing; a stale completion cannot resurrect a skipped candidate, replace a newer assessment, or overwrite owner answers and Telegram receipts. Telegram and Firestore still do not share a transaction: an edit already in flight can race a newer edit, and a retained pending update is reconciled on a later run without sending a new message.
- Each automatic screening claim atomically increments a persistent consecutive-failure counter before provider I/O. Three attempts without a completed assessment pause that item, including attempts interrupted before saving a result. Evidence-bearing pending and rejected/eligible assessments reset the consecutive counter. Historical total attempt counts remain separate; legacy failures are not retroactively invented.
- Paused items retain their pending/screening state and evidence. They are neither rejected nor counted as completed, cooling, or eligible. `screen_attention_remaining` keeps scans partial and appears in authenticated status and acceptance snapshots. Other due items can continue. After fixing the cause, an explicit `/competition URL` assessment with evidence can recover an item; an unsuccessful manual review does not silently rearm automatic retries.

## Validation boundary

Regression tests reproduce owner skips during both model work and Telegram editing, a newer assessment with the same timestamp, finite insufficient-evidence attempts, interrupted attempts, manual recovery, continued processing of healthy work, and partial outcomes for paused work. Production rollout and actual scheduled-run evidence must be recorded separately. These changes do not establish restoration of the two HTTP 403 announcement sources, sustainable long-term queue capacity, or a real eligible contest delivery.
