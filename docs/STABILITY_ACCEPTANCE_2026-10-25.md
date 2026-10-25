# Kairos sustained-operation acceptance

Observation date: 2026-10-25, Asia/Taipei. This is an ongoing, time-limited acceptance record, not a claim of long-term stability.

## Independently verified scheduled runs

Cloud Run request logs identify `Google-Cloud-Scheduler`, HTTP 200 and revision `kairos-git-205dd39` at 20:00:02, 21:00:01 and 22:00:01. The corresponding durable scan receipts are below. HTTP 200 means dispatch completed; all three scan outcomes remained `partial`.

| Actual schedule | Run | Seconds | New records | Assessment attempts | Rule failures | Queue before → after | New cards / edits | Stale sent assessments |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| 20:00 | `run-e629141aeb3948edb5675267ee88fa8f` | 105.37 | 1 | 2 | 0 | 74 → 73 | 1 / 1 | 1 |
| 21:00 | `run-6853141ecc0f4a75b6c7c11c581a10ca` | 88.45 | 0 | 9 | 9 | 73 → 73 | 1 / 1 | 0 |
| 22:00 | `run-3f1e1b3a414c4454a26a105963983cc0` | 64.09 | 0 | 9 | 8 | 73 → 72 | 1 / 0 | 0 |

Assessment queue departures inferred from the queue balances were 2, 0 and 1. Departures include evidence-bearing pending assessments, not just eligibility confirmations. The 21:00 notification came from already assessed work; nine failed source fetches did not become nine completed assessments. Historical receipts do not contain explicit first-attempt/retry counters, so those values cannot be reconstructed reliably and must not be invented.

Each run discovered 77 listing leads before canonical deduplication and attempted 23 listing pages. These are not 77 new candidates per hour: persisted new records were 1, 0 and 0. This establishes automatic continuation and rotating deduplication, not a measured sustainable arrival rate.

## Complete current snapshot at 22:45

The read-only snapshot `work/acceptance-baseline.json` found 72 pending assessments: 50 due, 22 cooling or leased, and 48 without a prior fetch report. The oldest due and untouched item was created 2026-10-24 20:00, approximately 26.75 hours earlier. Query sample saturation was false; the snapshot is complete at its current size, not a proof of arbitrary-scale capacity.

All ten `telegram_sent` records had message receipts; one was a previously labeled synthetic test. No Telegram uncertain/failed record, outreach uncertain record or pending edit was present in this snapshot. All current real delivered competition assessments were pending, not eligible. The original five stale delivered assessments had reached zero by the 21:00 scheduled run.

## Source access investigation

Ordinary local GET requests reached the public KMU homepage and the MOC news/RSS-directory pages. Those local results are not cloud coverage. A temporary job ran the same deployed container in `asia-east1`, without application secrets, and made one ordinary unauthenticated GET per official endpoint:

| Official public endpoint | Same-region cloud result |
| --- | --- |
| `https://hac.kmu.edu.tw/index.php/zh-tw/notice` | HTTP 403 |
| `https://hac.kmu.edu.tw/index.php/zh-tw/` | HTTP 403 |
| `https://hac.kmu.edu.tw/index.php/zh-tw/?format=feed&type=rss` (linked by its homepage) | HTTP 403 |
| `https://www.moc.gov.tw/` | HTTP 403 |
| `https://www.moc.gov.tw/News.aspx?n=105&sms=10550` | HTTP 403 |
| `https://www.moc.gov.tw/OpenData.aspx?SN=C4E4E3A8E687AD91` (linked by the official RSS directory) | HTTP 403 |

The job completed successfully at 22:37 and was deleted after its six structured receipts were saved to `work/cloud-source-probes.json`. No proxy, identity spoofing, challenge solving, login or access-control bypass was used. No alternate endpoint has demonstrated restoration from production cloud egress.

Impact: KMU's announcement coverage and MOC's central news/call coverage remain incomplete; exact missing-announcement counts and the full outage window are unknown. Search-index snippets and other existing sources do not establish complete substitution. Failure must not be reported as an empty announcement feed.

Recovery requires a normal public request from the production environment to obtain genuine readable source content, successful parsing, and a bounded catch-up review from the last proven successful fetch. If there is no prior successful receipt, the historical gap remains unknown. A new RSS configuration also requires narrowly validated URL-policy support and a production fetch/parse check; it must not be treated as connected merely because its URL exists. Public service restoration or an officially published, cloud-accessible alternative is required; third-party contact remains prohibited.

## Further fixes and validation

- `d4fbe82`: atomic persisted screening attempt counts and per-run metrics for new screening leads, requeues, retries, queue departures, evidence-bearing pending departures, source deferrals, cooldowns, untouched items and oldest due age. Counts start with this instrumentation; legacy attempt history is not fabricated.
- `2cea958`: after two HTTP 403/429 receipts from one origin in a run, defer additional candidates from that origin without claiming them; continue other sources within the unchanged global fetch/model limits. This addresses the observed 21:00 and 22:00 fetch-slot exhaustion. Deferred work remains visible and is not declared complete.
- `52219d6`: duplicate detection reads all stored sent/uncertain receipts with a bounded RPC timeout, rather than forgetting records after the first hundred. A failed history read prevents delivery instead of bypassing deduplication.
- `99054a3`: pending ready notifications and a saturated notification sample prevent full success even when a capped delivery succeeds. One predicate controls both card selection and outstanding-work counting.
- Automated validation: 244 tests passed, including same-origin denial isolation, first/retry metrics, duplicate suppression beyond 100 receipts, and partial status until a second queued notification is delivered. Compilation and Git whitespace checks passed.
- A proposed additional manual scan was rejected by automatic approval review because it could mutate production and send notifications while the acceptance tracking avoids repeated scans for evidence. It was not retried or bypassed. Validation uses health checks and actual Scheduler requests instead.

The read-only `scripts/audit_scan_acceptance.py` creates bounded, timestamped snapshots without triggering work or sending messages. New `screen_completed` means an item left the screening queue, including evidence-bearing pending decisions; it does not mean all eligibility conditions were established. `screen_queue_cooling` includes work unavailable under cooldown/lease rules, not completed work.

## Final rollout and actual 23:00 continuation

Revision `kairos-git-99054a3` passed health checks with DM automation disabled and received 100% of production traffic before 23:00. Cloud Run request evidence at 23:00:01.807 identifies this revision, `Google-Cloud-Scheduler` and HTTP 200. No additional manual production scan was executed in this acceptance session.

Durable run `run-9c10b45bdef34a16ae4568fe41763901` started at 23:00:01.822 and finished at 23:01:14.094 (72.27 seconds), correctly remaining partial:

- New screening leads: 0; screening attempts: 3; retry attempts: 0; queue departures: 1 (rejected); evidence-bearing pending departures: 0; requeues: 0.
- Two insufficient-evidence assessments stayed pending with cooldowns. One related rule-page fetch failed, but all three assessments obtained at least one source. Model/provider errors: 0.
- Queue: 72 → 71; due: 47; cooling/leased: 24; never attempted: 48 → 45. The oldest untouched identity advanced from `contest-0b739848d2af4732beadf0bf` to `contest-616807f43421ce774db8c102`, rather than repeatedly revisiting the same head.
- All three modeled items were first attempts. The new same-origin denial guard had no qualifying repeated-denial event in this run; its fault behavior is verified by regression tests, not falsely claimed as observed in production here.
- New cards: 0; card edits: 0; ready cards left: 0; failed/uncertain notifications: 0; stale sent assessments: 0. No eligible item was established.
- Both original announcement sources still returned HTTP 403. The 23-page listing rotation and deduplication continued without creating duplicates.

Across the actual 20:00–23:00 runs, one new record entered and four assessments left the screening queue, a net reduction of three (74 → 71). This short window shows effective automatic progress, including a change in the oldest pending identity. It does not establish sustainable long-term capacity, restoration of blocked sources, or final eligibility of pending candidates. The remaining oldest untouched batch is approximately 27 hours old, so monitor item identities and completion rates as well as age: many old items were imported within seconds of one another.

Latest read-only snapshot: `work/acceptance-2300.json`, copied to `work/acceptance-latest.json` for the bounded heartbeat. Original baseline remains `work/acceptance-baseline.json`.

## Bounded follow-up

Heartbeat `kairos` / Kairos 穩定性驗收 checks every six hours with a finite count of thirteen and an explicit deadline of 2026-10-28 23:00 Asia/Taipei. It notifies only for meaningful progress, failures, required decisions, or final expiry; ordinary queue changes stay quiet. At expiry, or when the next check would exceed the deadline, it must issue a final pass/fail record and stop this acceptance tracking. Kairos's own hourly business scheduler must remain enabled.

Acceptance is still open: sustained effective throughput, progress of the oldest due items, restored source completeness and a real eligible-item Telegram delivery have not yet been established. A temporary decrease in pending totals, a clean current round, or simulated delivery failures cannot close these gaps.
