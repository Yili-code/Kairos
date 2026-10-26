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

## Immediate repair evidence at 23:49 Asia/Taipei

- Atomic fixes: `0dcb851` protects refreshes, `e207ecb` bounds unresolved screening attempts, and `ea84aed` excludes the three observed student honor recaps while preserving new entry invitations. All 254 tests pass; compilation and whitespace checks pass.
- A one-shot job using the repair image and the existing runtime identity verified real Firestore transactions in `kairos_repair_validation`: one concurrent screening claimant, failure counters surviving interrupted attempts and stopping at three, stale-skip rejection, rejection of a newer assessment even with the same timestamp, and assessment-only writes preserving owner fields. All five checks passed, with zero production-candidate writes and zero Telegram calls. Its documents and temporary job were removed.
- Three explicitly identified pending student-award result announcements were archived as non-entry announcements using per-document version preconditions. Each retained a `competition.discovery_exclusion` reason, original title, and check timestamp. The one-shot repair made zero model or Telegram calls. It did not classify the underlying contests as ineligible or claim three completed eligibility assessments. Its temporary job was removed after the three successful receipts were saved.
- Revision `kairos-fix-ea84aed` serves 100% of traffic. Health is `ok`; authenticated status rejects unauthenticated requests. The owner-selected `gemini-3.5-flash-lite` model and disabled Threads DM automation remain in effect. The final image reuses the pinned dependency image from `kairos-fix-e207ecb` and copies the tested application sources; no dependency changes were introduced.
- The read-only post-repair snapshot found 68 pending assessments, 19 skipped records, ten sent Telegram records, and one draft-ready record. The reduction from 71 to 68 is the explicit recap cleanup, not scheduler throughput evidence. No additional production discovery scan was invoked.
- The next actual business schedule is 2026-10-26 00:00 Asia/Taipei. At this checkpoint there is no scheduled-run evidence for the new revision. Multiple actual rounds, sustainable queue progress, recovery of the two HTTP 403 sources, and a real eligible notification remain unverified. Existing finite acceptance tracking must continue; these repairs are not final acceptance.

Pull request: https://github.com/Yili-code/Kairos/pull/1. Automatic approval review rejected direct promotion to `main`; source remains on `codex/kairos-bounded-recovery` pending explicit merge approval. Production deployment was separately authorized and verified.

## New-candidate starvation repair (2026-10-26)

Discovery now persists the entire bounded announcement batch before allocating screening work. With more than one configured model slot, one newly created candidate gets an early attempt, then the existing queue keeps its original last-attempt order. Software/hackathon titles use the already declared profile priority only for this fresh turn; they do not establish qualifications or tool proficiency. Existing curated entries retain precedence over generic AI titles. A one-slot configuration keeps old work first.

A regression with eight old candidates and five fresh software leads confirms that the fresh candidate and two old candidates are evaluated within the same three-model ceiling, while all five fresh candidates are retained. A separate refresh/new/backlog test confirms all three share that same ceiling. Repeated listing results do not receive another fresh turn; source failures do not prevent healthy old work. This does not prove sufficient throughput for arbitrary arrival rates; production arrivals, departures, paused identities and ages must still be observed over real rounds.
