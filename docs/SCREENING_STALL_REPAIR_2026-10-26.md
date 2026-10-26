# Screening backlog diagnosis and repair — 2026-10-26

Scope: screening progress, official-rule handoff, bounded source failures and result persistence. No source-list expansion, recommendation-policy change, model change or paid-model-budget increase.

## Live baseline: the zero-completion premise had changed

At 13:00 Asia/Taipei the real hourly Scheduler invoked `/tasks/discover` on `kairos-review-54dea4c`. Cloud Run recorded HTTP200 and 86.00s latency; durable run `run-47266483f9cb4b26b38a2061b1cdac66` finished after85.90s with partial status. Partial remains appropriate: backlog and source-access gaps persist.

| Stage / outcome | Actual baseline evidence |
| --- | --- |
| New leads persisted | 20 |
| New-candidate claims/fetch attempts | 2 |
| New-candidate assessments saved | PayPal pending + HRI rejected, confirmed by stored facts, source receipts and matching save times |
| Total model attempts | 3: two candidate checks and one historical-card refresh |
| Terminal queue completions | 1, the HRI rejection |
| New eligible recommendations | 0 |
| Actual Telegram update | One existing calligraphy card, original message20, pending assessment, update_pending=false; not an eligible new recommendation |
| Unhandled candidate/model errors | 0 / 0 |
| Announcement source failures | 2, previously disclosed cloud403 gaps |
| Queue balance | 137 +20 new -1 terminal =156 pending |

The old `screen_completed` counter means **left the screening queue with a terminal decision**, not “a model assessment was saved.” PayPal did finish execution and save grounded facts; unknown AI creation permission, finalist attendance, publicity rights and uncertain estimates correctly kept it pending. Calling all pending results execution failures was inaccurate. They remain unresolved qualification work and must not be counted as completed recommendations. A further audit found that the HRI rejection itself used only the directory summary: it proves execution/persistence, **not** valid official qualification verification. Its terminal status therefore required correction rather than being offered as acceptance success.

The156 pending records consisted of113 without a saved rule-fetch receipt,19 with external fetch blocks,16 with saved but incomplete information and8 with only Contest Watchers summaries. “No saved fetch receipt” does not prove no historical legacy attempt. Oldest creation age was48.17h. The older schema did not record exact claim timestamps or every intermediate stage; these timestamps are explicitly unobserved rather than reconstructed as fact.

Local evidence: `work/stall-repair-20261026/before-current-audit.json`, `baseline-candidate-ledger.json`, `pre-repair-natural-edit-proof.json`. Raw credentials and private recipient details are excluded.

## Root causes and repairs

1. **Official-rule traversal stopped at summaries.** The actual Tactical Urbanism directory page has a `Visit Official Website` button inside its article footer. URL-keyword matching and generic footer suppression missed it, so the model consumed the directory summary and produced pending facts. Explicit official labels and the narrowly identified article-footer button are now retained. Directory copy is discovery-only, never rule evidence. An unsupported official target stays blocked under the existing host policy; no new host was added.
2. **The same handoff gap affects campus announcements.** The actual student-award page at `careercenter.ncu.edu.tw/news/show/3038` labels its external URL “官方網站：” but uses the URL itself as anchor text. The parser now follows that explicit in-paragraph context within existing permissions. Real read-only retrieval reached the already-permitted `contest.bhuntr.com` event page, which exposed empty application mount points and only15 characters of site title. Such pages are now `dynamic_rules_unavailable`. A required failed official handoff prevents spending a model slot on the parent summary; it does not invent missing rules or bypass a browser challenge.
3. **Blocked handoffs could monopolize the bounded fetch batch.** Per-origin isolation previously covered HTTP403/429 only. Missing/disallowed official links and dynamic/unsupported content now participate in the same two-failure isolation when they prevent rule verification. Controlled eight-blocked-plus-healthy replay processes two blocked records, defers six for that origin and still completes the following healthy candidate. The existing per-run model ceiling and overall fetch ceiling remain unchanged.
4. **Ordinary failures left opaque live claims.** A caught ordinary per-candidate exception now persists a safe exception class, last successful step and four-hour cooldown through the existing snapshot-guarded write. It preserves prior fields and consumes the existing three-attempt budget. Cancellation/crash still relies on the expiring lease and cannot silently reset attempts. Stale results remain unable to overwrite newer receipts or owner answers.
5. **Progress evidence conflated different outcomes.** Durable candidate reports now record claim, fetch status, model-slot usage, assessment outcome, save conflict, stop reason and notification eligibility. `screen_results_saved` includes saved failure diagnostics; `screen_checks_completed` counts saved successful assessments, including pending information; `screen_completed` continues to count terminal queue exits only. Unknown facts, paused work and source blocks never become terminal completions merely because metrics were added. Oldest pending creation time is retained separately from age since last attempt.

## Repair of affected historical exclusions

The same source defect affected eight skipped/rejected records whose only evidence sources were Contest Watchers summaries, including HRI. A bounded audit identified exactly these eight unsent records with no owner answers. They were restored to background pending verification by one atomic Firestore commit with per-document server-update-time preconditions. Prior assessments were preserved verbatim in `prior_assessment`; current unsupported facts were marked unknown. Recorded attempt totals were untouched, and the consecutive unresolved budget was conservatively preserved/consumed rather than reset. No messages or model calls occurred, and no qualification completion was claimed.

This correction adds8 to the operational pending queue:156→164 before the14:00 natural run. It is neither new discovery nor failed processing and must be shown separately in queue balance. It does not establish that any restored event is suitable. Receipt: `directory-rejection-repair-receipt.json`, commit time13:57:48 Taipei.

## Controlled evidence and limits

`official-handoff-before-after.json` replays the identical actual saved directory HTML and assessment through old/current code with controlled model/HTTP adapters: summary-model adapter calls1→0, explicit unsupported official target revealed, decision remains pending. This proves corrected traversal and avoided inappropriate model work; it does not prove real qualification or production throughput.

Focused workflow cases cover pending information saved without terminal completion, source isolation, ordinary-error cooldown/cap, cancellation/lease recovery, stale-snapshot rejection and unchanged notification gating. An allowed official handoff can reach assessment and terminal persistence in the controlled workflow. Model/Telegram adapters in these tests are substitutes; their receipts are not real deliveries.

The source20841dd runtime image completed an isolated actual-Firestore proof using the same workflow, transaction and query implementations. A normal case saved four results: one terminal assessment, two official-content blocks and one ordinary error. Six same-origin cases were deferred while the healthy candidate progressed. Concurrent claims admitted one owner; late results preserved newer delivery receipts and owner answers; retries paused after three failures; a controlled Telegram adapter was called once across reruns. There were zero real model calls, real Telegram calls or production candidate writes.

The real SDK stress case placed500 paused records before a healthy501st record with tied update timestamps. The first window retained501 unresolved records; the next window completed the healthy record and retained500 paused records. Read-only queries did not advance the cursor, and full collection paths had isolated cursor namespaces. Documents and cursor were deleted after verification; the temporary job was deleted at16:21 Taipei. `cursor-runtime-proof.json` records execution `kairos-stall-validation-20841dd-w25tb`. An earlier no-traffic revision failed startup because CollectionReference has no public `path` property; the final constructor stores its supplied collection path instead. That failed revision never received production traffic.

## Natural Scheduler evidence

All times below are2026-10-26 Asia/Taipei. HTTP request logs and durable run documents were both checked. These are actual hourly Scheduler requests, not manually triggered production scans.

| Round / revision | Claimed | Fetch requests | Model checks saved | Source-blocked | Result saves | Terminal exits | New leads | Queue balance |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
|14:00 / f452e23 |8 |8 |2 |6 |8 |0 |39 |164+39=203 |
|15:00 /136f979 |8 |15 |2 |6 |8 |2 unsupported exclusions |20 |203+20-2=221 |
|16:00 /136f979 |7 |12 |2 |5 |7 |0 |19 |221+19=240 |

The14:00 checks were All Tools Allowed Jam3 and the NTUA/Hua-Hsia call. Both were saved pending missing facts. Actual saved official text exposed two parser defects: a Chinese opening date was mistaken for a competing closing date, and a date-first English closing label/bare PM time was not recognized. Controlled replays of the same official content now resolve the NTUA deadline to2027-02-01 23:59+08 and the jam deadline to2026-10-26 17:00UTC. An explicit imperative to build with AI art/audio is recognized as artifact-creation permission. These are corrected facts, not eligibility claims. A guarded two-record fact-only correction at14:42 preserved statuses, attempt counters, receipts and original model-check timestamps; it is not a natural run result.

The15:00 terminal results were audited rather than accepted as successful drainage. AWS CDS Partner requires APN-employer authorization; the owner's employer affiliation is unknown, so it is not a proven disqualification. The other result mixed a featured Apple Vision Pro award from the Curious Refuge event catalogue into an older holiday contest. Current code preserves unknown affiliation, requires evidence that prizes are exclusively noncash, and blocks the multi-event catalogue as single-event rules. Both false exclusions were restored to background pending at16:20 using one atomic update-time-guarded commit. Prior assessments and attempt totals were retained, failure budgets were not reset, and a24-hour cooldown was applied. No model or Telegram calls occurred. Consequently the corrected backlog is242, including this separate+2 data correction; these two terminal exits do not establish valid completed qualification.

The16:00 run saved a new official-source assessment and a second attempt for another candidate; both remain pending unknown requirements. Three unapproved official handoffs and two HTTP403 candidates were isolated;21 same-origin cases were deferred. All three rounds had zero ordinary candidate exceptions and zero result-save conflicts. They each used two candidate model calls plus one historical-card refresh, exhausting the existing three-call shared budget. These observations establish saved processing, not adequate throughput.

The oldest unresolved record at16:00 was `contest-425ac9c1ff9514307c7ed519`, created2026-10-24 12:55:15 Taipei, about51.1 hours old. It remains unresolved; last-attempt age must not replace creation age. The16:00 queue contained174 never-attempted records,59 cooling records and181 due records. Counts are not recommendations, and a paused record is not a completed record.

Historical Showrunner, calligraphy and Zhongshan Youth Art refreshes are not eligible new deliveries. Where a refresh lacked complete information, its old receipt was retained and the update was held with a bounded retry. The13:00 calligraphy edit has a real edit receipt, but predates the latest repair. No real eligible new-card delivery has been established for this repair.

## Authorized official-rule handoffs

The owner explicitly authorized organizer rule domains for existing candidates while prohibiting discovery expansion. Four reviewed existing primary URLs now have verification-only scoped handoffs: Photora2026, Global Sustainability2026-27, KLPA AUTOPORTRAIT2026 and the43rd Chicago Latino Film Festival poster contest. The discovery host list, feeds, activity types and search terms are unchanged. Reviewed official pages must pass edition/content markers; a mismatch remains pending without a model call. An unavailable optional directory parent cannot block readable required official rules. Origin isolation follows the organizer rather than the directory for these cases.

A read-only fetch through the actual bounded fetcher obtained3,3,2 and1 official text pages respectively, without model, Telegram or candidate writes (`reviewed-official-fetch-proof.json`). This proves retrieval locally, not cloud access or natural qualification. Global Sustainability FAQ answers were not readable in extracted text; questions do not prove AI permission. KLPA explicitly bans AI prompt-generated images in whole or part; Photora and Chicago bans on fully AI-produced work do not by themselves prove that partial AI production is either permitted or prohibited. The latter case remains unknown. No application, payment or organizer contact occurred.

Fetch/text budget exhaustion is now a required-rule failure: partial content is retained as evidence but cannot consume a model slot or establish a qualification decision. Controlled cases cover reviewed handoff success after a directory403, edition mismatch, unchanged global host permissions, partial-AI uncertainty and exhaustion after reading only partial sources.

## Release and remaining acceptance gaps

Source20841dd received100% traffic at16:17; source dbb208b at16:23. Neither received the16:00 request, which ran136f979. Source b884e50, including the fetch-budget guard, received100% traffic at16:28 after exact-package validation. No natural Scheduler request has yet run this revision. Deployment receipts identify the current revision and time separately from natural execution evidence. The live `/start` implementation, primary/fallback model, source configuration, policy, three shared model slots and disabledDM are retained. Canonical hourly Scheduler remains enabled; status is protected and obsolete tags are cleared.

**Acceptance has not passed.** The newest cursor, negative-evidence and reviewed-handoff changes still need natural Scheduler execution. There are no proven valid terminal exits across14:00–16:00 after correcting the unsupported exclusions; arrivals exceed successful complete qualification. External403s, JavaScript-only pages, unreviewed organizer domains and missing official facts remain real blockers. The24-hour information cooldown and three-attempt cap limit waste but do not turn unknowns into completed work. Model capacity and the old-card refresh share are observed constraints, not permission to silently change configured budgets or recommendation policy.

Continue bounded natural-run observation until2026-10-28 23:00 Taipei. Report genuine terminal exits, saved pending checks, blocked/paused counts, oldest creation time, arrivals and actual notification receipts separately. If no eligible result exists, report that fact and its blockers. Never retry uncertain delivery automatically, manufacture a recommendation, treat HTTP200 as complete success, or claim sustained drainage from controlled tests.
