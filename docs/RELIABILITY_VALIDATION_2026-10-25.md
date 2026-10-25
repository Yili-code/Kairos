# Kairos reliability validation — 2026-10-25

All displayed times below use Asia/Taipei. This record distinguishes tested recovery from unresolved source completeness and sustained capacity.

## Release

- Production traffic: 100% `kairos-git-205dd39`; application Git SHA `205dd39`. Earlier recovery revision `6f89d9e` handled the observed 19:00 scheduled run.
- Atomic application commits: `20cdb7e` (queue, source isolation, delivery updates), `6f89d9e` (persisted unresolved-work success criteria), `205dd39` (bounded listing rotation).
- Scheduler `kairos-opportunity-scan` is enabled hourly (`0 * * * *`, Asia/Taipei). Existing 600-second Cloud Run/Scheduler deadlines remain. The workflow timeout is 480 seconds; the shared scan lease is 600 seconds.
- Original checkout modifications were preserved. No registration, payment, terms acceptance, organizer email, Threads DM, public reply, or uncertain-send retry was performed.

## Verified baseline and causes

The real 08:00 scheduled run remained partial: 75 pending assessments, three announcement errors, three insufficient-evidence analyses, one oversized rule page, no new notification. Scheduler itself reported no dispatch error.

- New-source screening ran before an unordered, mixed-status backlog. There was no fair persisted last-attempt order; bounded reads could conceal older work.
- The announcement parser always selected the first 20 links. The live AI-film page reported 26 distinct permitted leads: fixed truncation permanently omitted tail links.
- Shared-origin pacing could race after waking once, causing the Senao board to be skipped. Both Senao listing pages subsequently fetched successfully after bounded rechecking with a small timing margin.
- `hac.kmu.edu.tw` and `www.moc.gov.tw` consistently returned HTTP 403 from production. These remain unresolved access failures, not successful empty sources. Their missing coverage cannot be quantified from available data.
- The old schedule allowed at most six model evaluations per day before retries and refreshes. Sent assessments had no scheduled refresh/update worker.

## Changes

- Query by persisted `updated_at`, process pending/screening work before fresh leads, retain atomic claims and retry cooldowns, and provision the matching Firestore composite index (READY).
- Isolate unexpected board exceptions and retain per-page source receipts in durable scan records. Existing bounded transient HTTP retries and later scheduled retries remain active; 403 is not blindly retried inside a single request.
- Rotate the 20-link extraction window hourly. A deterministic test covers all 26 leads in two batches; the final production scan actually persisted four previously unseen canonical records.
- Refresh at most one delivered assessment per run using the shared model budget. Persist `update_pending` before editing the original Telegram message; retry the edit after lost acknowledgement. An identical accepted edit is treated as idempotent success. There is no fallback to a new message.
- Keep unprocessed due assessments, source deferrals, failed/uncertain notifications, and stale/pending card updates visible as partial outcomes. Notification uncertainty still requires manual reconciliation.
- Continue hourly while retaining the three-evaluation per-run cap. The nominal ceiling is 72 model evaluation slots/day; refreshes, failures and retries consume slots. This is a ceiling, not measured sustainable throughput.

## Evidence

| Kind | Result |
| --- | --- |
| Automated simulation | 237 tests passed; includes fair queue rotation, partial-outcome criteria, independent source failures, fixed-cap lead recovery, explicit rejection/retry, interrupted delivery uncertainty, and lost edit acknowledgement |
| Build checks | Application/scripts/tests compilation and Git whitespace checks passed |
| Manual synthetic real-provider integration | Clearly labeled owner-only card: persisted success after Telegram acceptance, repeated delivery suppressed, original message edit accepted; synthetic record subsequently marked skipped |
| Manual real scan on `6f89d9e` | `run-19185cb24eac4921a212829cd80d49fb`, approximately 77 seconds; queue 75 → 74, one existing card updated, no new card, two insufficient-evidence assessments; source errors reduced to the two 403s |
| Actual 19:00 Scheduler run on `6f89d9e` | `run-ae6a488b99f94ba8ba59c6acbaa2e0e0`, approximately 111 seconds; queue 74 → 72, one real pending candidate card sent with persisted receipt, one existing card updated; no model/rule-fetch/card errors; Scheduler lastAttemptTime 19:00:00 and no reported dispatch error |
| Manual real scan on final `205dd39` | `run-c833c15978704a16b6d379441d81ec63`, approximately 130 seconds; four new canonical leads recovered, two pending items completed, queue 72 → 74; one real pending card sent and one existing card updated; no model/rule-fetch/card errors |

The last two scans each observed 23 listing pages, two HTTP 403 source errors, three model evaluations and zero eligible contests. Both new real cards were pending recommendations, not verified eligible entries. Telegram acceptance is not a human read receipt.

## Remaining validation and limits

- All three scans correctly remained partial. Latest state: 74 pending assessments (68 currently due), two sent assessments needing refresh, zero failed/uncertain Telegram notifications.
- The two 403 sources still have an unquantified coverage gap; no complete-source-coverage claim is justified. A previously oversized Chroma rules page was not independently revalidated by these scans.
- No real eligible contest was established, so the positive eligible-notification path is covered by simulation, not a real qualifying production event. Production rejection/retry and lost-ack scenarios were simulated rather than intentionally induced against Telegram.
- Three scans establish continuation and useful progress, not sustained queue stability. Five items left the assessment queue while four new tail leads were recovered. Track unique ingress, completed assessments, cooldown work, oldest due age and execution duration over multiple days before claiming demand remains below capacity.
- Queue/status inspection is bounded at 500 records. Saturation is reported as partial for the screening sample; this is not an unbounded queue census or a proven arbitrarily large-scale scheduler.
- The next actual run is 20:00 on 2026-10-25, then hourly. It must execute on `205dd39`, persist a new run receipt, rotate source extraction, continue different due candidates, refresh another stale delivered assessment when possible, and preserve existing Telegram receipts. Source failures and outstanding work must remain partial. Zero eligible items must not be presented as successful verification of a real eligible notification.
