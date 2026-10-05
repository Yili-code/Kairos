# Kairos

Kairos is an owner-only opportunity funnel for YiLi. It finds public Threads posts about hackathons, internships, and paid projects; performs a conservative first-pass screen; asks button-first questions in Telegram; produces an evidence-grounded fit assessment and private-message draft; and sends only the exact draft YiLi approves.

This is intentionally not an autonomous outreach bot. Discovery can run unattended. External communication cannot.

## Current scope

- Threads only; source adapters can be added later.
- Priority: hackathon, internship, paid project.
- Schedule: 08:00 and 20:00 Asia/Taipei.
- Maximum three new Telegram opportunity cards per run.
- English and Traditional Chinese discovery terms are enabled by default.
- Threads discovery explicitly uses Meta's `RECENT` keyword-search mode and requires `threads_basic` plus `threads_keyword_search` approval.
- Term-time target: 13–16 hours per week.
- Remote preferred; onsite work in Taipei or Keelung is acceptable; overseas and fixed cross-time-zone meetings are acceptable.
- Unpaid trials are limited to 5–8 total hours, cannot be used directly in a commercial product, and require explicit IP terms.
- If Threads DM is unavailable, the workflow stops. It never posts a public reply as a fallback.

## Why this design

The official Threads API is suitable for keyword discovery, while Threads DM currently requires a separate UI adapter. Keeping those boundaries separate prevents a login expiry or UI redesign from stopping discovery and preserves a strict human approval gate.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the state machine and failure policy.

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
5. Configure Cloud Scheduler for `0 8,20 * * *` with timezone `Asia/Taipei`, calling `POST /tasks/discover` and supplying `X-Scheduler-Secret`.
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
- Temporary Gemini 429/5xx failures receive one silent retry. Persistent primary-model overload falls back to `gemini-3.5-flash-lite`; persistent failure preserves the answers and shows a manual retry button.
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
