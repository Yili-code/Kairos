# Kairos

Kairos is an owner-only opportunity funnel for YiLi. It finds public Threads posts about hackathons, internships, paid projects, and AI-assisted online competitions. Collaboration opportunities use a button-first Telegram questionnaire and an evidence-grounded private-message draft sent only after exact-draft approval. Competitions use a separate rules-and-effort assessment and never enter the outreach workflow.

This is intentionally not an autonomous outreach bot. Discovery can run unattended. External communication cannot.

## Current scope

- Discovery uses Threads plus public campus, government, foundation and competition-directory announcements; supported organizer pages can also be reviewed with `/competition <https-url>` in the owner Telegram chat.
- Existing priorities remain hackathon, internship, paid project; direct-entry competitions are screened independently.
- Schedule: 08:00 and 20:00 Asia/Taipei.
- Maximum three new Telegram opportunity cards per run.
- English and Traditional Chinese discovery terms are enabled by default.
- Threads discovery explicitly uses Meta's `RECENT` keyword-search mode and requires `threads_basic` plus `threads_keyword_search` approval.
- Term-time target: 13–16 hours per week.
- From the 2027 winter break onward, winter and summer breaks may allow more time; exact weekly hours remain unconfirmed and must not be promised.
- Remote preferred; onsite work in Taipei or Keelung is acceptable; overseas and fixed cross-time-zone meetings are acceptable.
- Unpaid trials are limited to 5–8 total hours, cannot be used directly in a commercial product, and require explicit IP terms.
- If Threads DM is unavailable, the workflow stops. It never posts a public reply as a fallback.

## Why this design

The official Threads API is suitable for keyword discovery, while Threads DM currently requires a separate UI adapter. Keeping those boundaries separate prevents a login expiry or UI redesign from stopping discovery and preserves a strict human approval gate.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the state machine and failure policy.

## AI-assisted online competitions

The goal is cash prizes and publicly demonstrable awards, with AI doing at least 50% of production. Taiwan and international contests, English submissions, and any artifact type are in scope. Online finalist Q&A is acceptable; physical attendance is not.

- Estimate the full process, including planning, AI generation/waiting, review, submission, preparation, revisions and later-round Q&A. There is **no fixed six-hour ceiling**: time is part of the return decision. Waiting for judging results is not work time.
- Prefer the existing ChatGPT subscription. Additional tools, API calls, compute and hosting are evaluated against potential return, with **no fixed NT$300 ceiling**. Registration fees are separate, displayed explicitly, and require YiLi's own decision. No fee is paid automatically.
- Prefer free registration and no presentation. Paid entry and online finals may qualify but rank lower.
- Explicit substantial-AI permission is required. An AI theme, an AI API requirement, or silence about AI does not establish permission for AI to produce the work.
- Official evidence is required for deadlines/timezones, cash prizes, public winner recognition, eligibility, entry format, finalist/award attendance, public-display rights, deliverables, and IP terms. Missing facts remain **pending**, never inferred as free or allowed.
- All time, production-share, and tool-cost estimates are visibly labeled AI estimates. Passing the filter does not predict an award or guarantee completion within the estimate. Unbounded estimates remain pending.

The discovery goal includes overlooked, small-scope calls with low production effort and worthwhile cash prizes, not just prominent technology hackathons. Campus or local origin is a discovery lead, **not proof of low participation**. Entrant counts and prize slots are displayed only with source evidence; unknown remains unknown. The model never estimates winning odds or expected winnings. Estimates at two hours or less receive a small ranking preference, not a promise of a two-hour award.

Competition search terms are separate from existing Threads terms, so existing installations receive the new category without overwriting customized collaboration searches. Eighteen bilingual terms cover campus AI/video, posters, writing, art and foundation contests. Twenty-four default public sources include campus/department and arts announcements, youth/education/culture agencies, a foundation, a microfilm association, international contest directories, the public Devpost listing, Unreal RSS and itch.io jams. Listing responses are bounded at 1 MB; each run can read all 24 default sources, with a maximum of two pages per source. Custom lists above the 24-source limit rotate by half-day. Listings may be partial, dynamic or blocked; successful HTTP access does not establish complete institutional coverage. AI Film Contests supplies organizer/platform links only; its summaries are not used as rule evidence. Result recaps and listing self-links are excluded.

Automatic model screening is capped at three contests per run. Blocked sources do not consume a model slot; fetch attempts have a separate cap of three times the configured screen limit. Only eligible competitions with sourced prize, future deadline, deliverables, AI rules and usable effort estimates may be automatically delivered; incomplete or pending assessments remain in bounded background recovery. Explicit owner resends also pass the final information gate. Fresh announcement calls explicitly mentioning AI are screened before the generic backlog; remaining backlog is processed oldest first. Unscreened leads are retained as `competition_pending_screen` in Firestore. Atomic screening claims expire after ten minutes if a process dies, allowing later recovery. Undelivered screened cards stay in Firestore for later runs. Known event URLs deduplicate multiple social posts for the same contest. Scan results count eligible, pending, rejected, source failures and analyses without quoted evidence separately.

Rules are fetched only from configured HTTPS hosts, including selected AI-film organizers and submission platforms. Fetching rejects credentials and validates every HTTPS redirect (three hops maximum, one retry per transient failure) and permits only bounded, known public navigation queries; tracking tokens and arbitrary actions are rejected. Devpost event links also request `/rules`. HTML notices may link PDF attachments and related terms, rules, timeline or entry pages within a six-document cap and a 45-second total retrieval budget. PDFs are limited to 3 MB and 20 text pages; malformed, encrypted and image-only documents do not provide positive evidence. Long text remains pending if truncated. Quoted evidence must occur in a fetched page/document at its exact URL. Explicit AI permission is evaluated per component: a short human-only explanation does not automatically ban AI-generated images/video, and its work is reserved for the entrant. AI production share describes artifact production, while the total effort includes all human decisions, review and waiting. Unsupported, blocked or incomplete sources remain pending; there is no claim of comprehensive web discovery or independent legal interpretation.

Send `/competition https://event.devpost.com/rules` in Telegram to request a fresh review or recheck a known event. This command may update its assessment and send a card; it does not draft contact messages. Competition cards have only source and skip buttons. All competition callbacks and direct-send paths reject outreach, registration, payment, and submission.

Cards lead with the event name and decision, followed by cash prizes, a Taiwan-time deadline, registration fees and clearly labeled AI estimates. Known entry rules remain visible; unknown fields are grouped instead of repeated, and the first four blockers plus the remaining count keep incomplete assessments readable. Source quotes/links and the distinction between registration fees, tool costs and unverified winning odds are preserved.

Cloud Run continues to use the existing Gemini API configuration for screening. **ChatGPT subscription quota is not API credit** and is not called by the server; the subscription preference concerns making contest entries, not replacing Kairos's existing model backend. No new paid service is required by this feature.

| Optional variable | Default / meaning |
|---|---|
| `COMPETITION_SEARCH_TERMS` | Eighteen bilingual competition searches; empty disables those Threads searches |
| `COMPETITION_SCREEN_LIMIT` | `3`, bounded to 0–10 new contest analyses per scan |
| `COMPETITION_RULES_HOSTS` | Administrator-controlled HTTPS fetch allowlist; defaults are defined in `app/config.py` |
| `ANNOUNCEMENT_SOURCE_URLS` | Newline-separated public HTML/RSS/Atom listing URLs; empty disables announcements; over 12 pages rotate in half-day batches |

Read-only official-page/model verification (uses the existing authenticated Google Cloud account, writes no Firestore data, sends no Telegram message):

```powershell
.venv\Scripts\python scripts\verify_competition_screening.py https://event.devpost.com/rules
```

## Local quick start

Requirements: Python 3.12+, a Telegram bot/private chat, a Meta Threads app with keyword-search permission, a Gemini API key, and a Google Cloud project with Firestore.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Fill `.env` locally. Never commit it. Then load the variables into the process using your preferred secret-safe method and run:

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Check `GET /health`. A healthy process does not prove Threads, Gemini, Telegram, Firestore, or DM delivery; each integration needs its own controlled check.

## Required configuration

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API credential |
| `TELEGRAM_OWNER_CHAT_ID` | Only accepted Telegram chat |
| `TELEGRAM_WEBHOOK_SECRET` | Validates Telegram webhook requests |
| `SCHEDULER_SECRET` | Protects the discovery endpoint |
| `THREADS_ACCESS_TOKEN` | Official Threads keyword-search access |
| `GEMINI_API_KEY` | Fit assessment and message drafting |
| `GOOGLE_CLOUD_PROJECT` | Google Cloud project containing the runtime |
| `FIRESTORE_DATABASE` | Isolated named database; production uses `thread-opportunity` |
| `THREADS_DM_AUTOMATION_ENABLED` | Must remain `false` until a live UI check passes |
| `THREADS_STORAGE_STATE_JSON` | Authenticated browser state, supplied only through Secret Manager |

Production should inject all credentials from Secret Manager. Browser storage state must never appear in deployment commands, logs, source control, or Telegram.

## Telegram webhook

Configure Telegram's webhook URL as:

```text
https://SERVICE_URL/telegram/webhook
```

Set Telegram's webhook `secret_token` to the same value as `TELEGRAM_WEBHOOK_SECRET`. The application checks both that header and `TELEGRAM_OWNER_CHAT_ID`.

## Cloud Run deployment

1. Create an isolated Firestore Native database named `thread-opportunity` and grant the runtime account conditional access to that database only.
2. Store the Telegram token, webhook secret, scheduler secret, Threads token, Gemini key, and optional browser state in Secret Manager.
3. Build and deploy the provided Dockerfile to Cloud Run.
4. Grant the runtime service account Firestore access and secret access only for the named secrets.
5. Configure Cloud Scheduler for `0 8,20 * * *` with timezone `Asia/Taipei`, calling `POST /tasks/discover` and supplying `X-Scheduler-Secret`. Use 600-second deadlines for both the Scheduler HTTP attempt and Cloud Run; discovery has an eight-minute soft work budget and reports deferred search terms.
6. Register the Telegram webhook and perform one private-chat test.
7. Leave DM automation disabled until a controlled test account confirms the current Threads selectors and verifies the actual destination.

For background work outside request handling, use the appropriate Cloud Run billing/CPU configuration. The current design performs discovery within the authenticated scheduler request, so no free-running loop is required.

The helper scripts keep credentials out of command output:

```powershell
.venv\Scripts\python scripts\readiness_report.py
.venv\Scripts\python scripts\configure_telegram_webhook.py
.venv\Scripts\python scripts\configure_scheduler.py
```

`configure_scheduler.py` fails closed unless the Threads token exists and Cloud Run is already in production mode. Register the Telegram webhook only after the previously exposed bot token has been revoked and replaced.

## Reliability behavior

- Free-text answers use Telegram Force Reply markers bound to one candidate. If multiple opportunities are waiting, an unthreaded reply is rejected instead of being attached to the newest candidate.
- Hackathons ask for a preferred role, internships ask for the compensation condition, and paid projects ask for the preferred engagement structure.
- Gemini treats post text as untrusted data and uses a validated structured-output contract.
- Gemini defaults to `gemini-3.5-flash-lite` as the primary model. Temporary 429/5xx failures receive one silent retry. A distinct configured fallback is attempted on persistent transient failure; identical primary/fallback names are deduplicated. Persistent failure preserves the answers and shows a manual retry button.
- Draft-generation retry cannot approve or send a message. The exact-draft approval hash remains mandatory.

## Approval invariant

The Telegram approval applies to one candidate and one SHA-256 hash of the displayed draft. If the text changes, approval becomes invalid. Before the external action, the record moves to `sending` and receives a unique attempt ID. An unknown result becomes `send_uncertain` and is never retried automatically.

## Validation

```powershell
python -m pytest -q
python -m compileall -q app tests
```

Local tests cover ranking, bilingual search defaults, deduplication, current profile constraints, candidate-bound free text, category-specific questions, recoverable Gemini failure, prompt-injection boundaries, primary-model fallback, exact-draft approval, changed-draft rejection, and fail-closed DM behavior. They do not prove live Meta, Telegram, Threads, or browser-DM integration.

## Evidence policy

Drafting uses only the profile in `app/profile.py`. Existing technology names are not automatically treated as expert-level skills. InnoServe 2026 is ongoing, programming-competition details remain incomplete, and no model-generated claim may strengthen either fact without new evidence from YiLi.

## Evidence and recovery after three live rounds

Model facts select immutable source-span IDs; the application restores the original quote and URL. Equivalent encoded document URLs and CJK layout differences preserve provenance without accepting paraphrases. Free entry and deadline timezones require explicit evidence. Online entry does not prove no attendance; organizer exhibition does not establish entrant display rights. AI production share is calculated from weighted artifact components; human-only components require their own quoted rule. Unknown finalist work or unsupported restrictions prevent eligibility. Uncertain estimates remain pending rather than confirmed exclusions; AI production and evidence requirements remain; the owner removed fixed time and tool-cost ceilings on 2026-10-26.

Empty assessments return to the durable screening queue, with a four-hour transient/model cooldown or a twenty-four-hour blocked-source cooldown. Atomic claims enforce the due time; a candidate is attempted at most once per run. Curated public-rule seeds and related-document URLs are maintained explicitly in app/config.py. They are not automated web search or pre-approved facts, and disabling announcement URLs also disables the seeds. Cards prioritize rule PDFs and terms and show concrete questions for owner review; none of these questions are sent externally.

See [the three-round live record](docs/COMPETITION_ROUNDS.md) for remaining questions. The read-only audit can be repeated with `python scripts/audit_competition_round.py --round 3 --output work/round-3.json`; it uses existing authenticated Google Cloud/Gemini access and performs no Telegram or Firestore writes.
