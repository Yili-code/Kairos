# Kairos verification record

Verification date: 2026-10-24 (Asia/Taipei). The expanded competition workflow was verified in production through real discovery, owner-only Telegram delivery and persisted state. Telegram API acceptance is not proof that the owner read the message.

## Verified expanded rollout

- Revision `kairos-git-e6096e6` served 100% of traffic. Its `KAIROS_GIT_SHA` matched `e6096e6e9dd3673f63e8b500c4fb8577ad0a7d53`.
- Cloud Run and Scheduler deadlines are both 600 seconds; the 08:00/20:00 Taiwan schedule is unchanged.
- Health, disabled DM automation and rejection of an invalid scheduler credential were verified.
- A clearly labeled synthetic contest card was accepted by Telegram and persisted in Firestore. A real historical competition was reviewed through the deployed Telegram webhook, returned HTTP 200 and persisted a rejected assessment without approval/send claims.
- One real expanded discovery scan returned HTTP 200: **15 new leads, 3 contest analyses, 1 pending candidate card, 0 search errors, 0 card errors, 0 deferred search terms**. Twelve announcement pages were attempted with one source error. Fifteen leads are not fifteen qualifying entries; no eligible contest was established by this scan.
- A subsequent state audit found **12 unscreened contest leads retained for later scans**, one delivered real pending contest and zero contest outreach approval/attempt/sent claims. The synthetic test record is labeled separately.
- The verification client waits up to the same 600-second bound as the deployed scan. Later documentation/verification-only commits do not change the deployed application code.

## Existing production baseline

- Cloud Run service `kairos`, project `yili-chronos-prod`, region `asia-east1`, served revision `kairos-git-75ce1b0` before this change.
- The live health endpoint returned `ok`, production mode, configured Firestore/Gemini/Threads, and disabled DM automation.
- Scheduler `kairos-opportunity-scan` was enabled for `0 8,20 * * *` in `Asia/Taipei`; its last attempt was 2026-10-24 at 08:00 Taiwan time with no reported status error.
- Existing secrets and runtime identity are reused. No new paid provider, automatic registration, payment, entry submission, or outreach permission is introduced.

## Competition feature validation

- Python 3.12 local validation: **122 tests passed**. Coverage includes official-quote provenance, hard policy limits, unknown facts, deadline timezone and expiry, cash versus noncash prizes, separate registration fees, bounded requests and screen count, event deduplication, durable lead/card queues, atomic card/screen claims, expired analysis leases, unsafe links, oversized or truncated rules, Unicode card limits, HTML/RSS/Atom discovery, PDF text/attachment extraction, rotating source batches, time-budget deferral and blocked contest outreach paths.
- Compilation succeeded for application, scripts and tests.
- A read-only real-rule/model check against `https://hackthenet2026.devpost.com/rules` fetched one official page and validated nine evidenced facts. The report rejected the entry, including AI-use, eligibility, deadline, and workload conflicts. This was an integration sample, not a recommended contest.
- The configured primary model returned a transient HTTP 503 during validation. Competition analysis now uses the existing configured fallback on transient failures, with one attempt per model. The configured models were not changed.
- Expanded-source check: twelve configured public listing pages were attempted; eleven responded successfully and one foundation page was rate-limited. The corrected listing/title filter yielded six candidate leads in that sample, before later keyword expansion. These are discovery leads, not qualifying competitions or complete site coverage.
- PDF parsing was validated with locally generated text PDFs and mocked attachment responses. Two historical university PDF URLs could not be fetched during live checks and remained pending; live PDF-source integration is therefore not established by those examples.
- Discovery uses an eight-minute soft work budget; unfinished leads remain durable and unattempted search terms are counted separately. The matching 600-second Cloud Run/Scheduler deadlines were verified after rollout.

## Rollout verification

`scripts/verify_competition_screening.py` is read-only and sends no Telegram messages. `scripts/verify_competition_production.py` has explicit production side effects: it sends a clearly labeled owner-only test card, persists that synthetic test record, runs one real organizer-rule review through the deployed Telegram webhook, and optionally runs a production discovery scan with `--discover`.

The synthetic card is not evidence of a real qualifying contest or a human reading it. Live page/model validation is not evidence of award probability, six-hour production performance, or complete contest coverage. Quote matching establishes source provenance; the owner still checks the organizer's actual terms before entering. Threads DM delivery remains disabled and unverified.
