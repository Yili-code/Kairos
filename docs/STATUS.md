# Kairos verification record

Verification date: 2026-10-24 (Asia/Taipei). This file records pre-rollout evidence for the competition feature; verify the deployed revision independently with the production smoke script.

## Existing production baseline

- Cloud Run service `kairos`, project `yili-chronos-prod`, region `asia-east1`, served revision `kairos-git-75ce1b0` before this change.
- The live health endpoint returned `ok`, production mode, configured Firestore/Gemini/Threads, and disabled DM automation.
- Scheduler `kairos-opportunity-scan` was enabled for `0 8,20 * * *` in `Asia/Taipei`; its last attempt was 2026-10-24 at 08:00 Taiwan time with no reported status error.
- Existing secrets and runtime identity are reused. No new paid provider, automatic registration, payment, entry submission, or outreach permission is introduced.

## Competition feature validation

- Python 3.12 local validation: **111 tests passed**. Coverage includes official-quote provenance, hard policy limits, unknown facts, deadline timezone and expiry, cash versus noncash prizes, separate registration fees, bounded requests and screen count, event deduplication, durable card queue, atomic card claims, unsafe links, oversized rules, Unicode card limits, and blocked contest outreach paths.
- Compilation succeeded for application, scripts and tests.
- A read-only real-rule/model check against `https://hackthenet2026.devpost.com/rules` fetched one official page and validated nine evidenced facts. The report rejected the entry, including AI-use, eligibility, deadline, and workload conflicts. This was an integration sample, not a recommended contest.
- The configured primary model returned a transient HTTP 503 during validation. Competition analysis now uses the existing configured fallback on transient failures, with one attempt per model. The configured models were not changed.

## Rollout verification

`scripts/verify_competition_screening.py` is read-only and sends no Telegram messages. `scripts/verify_competition_production.py` has explicit production side effects: it sends a clearly labeled owner-only test card, persists that synthetic test record, runs one real organizer-rule review through the deployed Telegram webhook, and optionally runs a production discovery scan with `--discover`.

The synthetic card is not evidence of a real qualifying contest or a human reading it. Live page/model validation is not evidence of award probability, six-hour production performance, or complete contest coverage. Quote matching establishes source provenance; the owner still checks the organizer's actual terms before entering. Threads DM delivery remains disabled and unverified.
