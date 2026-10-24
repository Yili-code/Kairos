# Kairos architecture and safety contract

## Pipeline

1. Cloud Scheduler calls `POST /tasks/discover` twice a day.
2. The official Threads keyword-search endpoint returns recent public posts.
3. A deterministic first-pass scorer classifies and ranks opportunities.
4. Firestore deduplicates every Threads post ID before Telegram delivery.
5. The owner answers a button-first questionnaire in Telegram. One category-specific question captures hackathon role, internship compensation, or paid-project engagement preferences.
6. Free-text concerns and revisions must reply to a candidate-bound Force Reply marker when more than one opportunity is waiting.
7. Gemini receives the untrusted post data, the verified profile, and the owner's answers. It returns a schema-validated fit assessment and one private-message draft.
8. Telegram displays the exact draft. `Approve & Send` authorizes only that draft hash for that candidate.
9. The isolated browser adapter attempts a Threads DM. A missing DM action never falls back to a public reply.

## State transitions

### Competition branch

Direct-entry contests use `ai_competition`, not collaboration questionnaires. Threads keywords and bounded public HTML/RSS/Atom announcement lists discover candidates; `/competition <url>` also supports owner-requested source-page review. The category excludes existing internship/paid-project classifications and explicit hackathon teammate recruitment. Default sources cover campus/departments, education/youth/culture agencies, a foundation, a microfilm association and an international directory. More than twelve configured announcement pages rotate in half-day batches. Each source failure is isolated and counted; HTTP access alone does not establish complete site coverage.

`CompetitionScreener` fetches at most two allowlisted HTTPS documents without redirects, proxies or credentials. Known public navigation queries are supported; tracking/authentication parameters and arbitrary actions are rejected. HTML is capped at 256 KB and 32,000 text characters. A notice can link one allowlisted PDF within the same document budget; PDFs are capped at 1 MB, 20 pages and bounded text. Encrypted, malformed and image-only PDFs provide no positive evidence. Truncated text always prevents eligibility. Each fact includes a value, verbatim quote and exact source URL; unmatched quotes/URLs are downgraded to unknown. No source documents means no model call. Network/schema/model failure produces a pending report.

The deterministic evaluator owns limits: six hours summed across planning, generation/wait, review, submission and finals; AI production share at least 0.90; extra tools at most NT$300. Paid registration requires an evidenced amount/currency but has no invented monetary cap. Cash prizes, public recognition, public display rights, eligibility, deadline timezone and all-round attendance must be supported. Uncertainty prevents eligibility. Source-derived facts and model estimates are separately stored on the backward-compatible `Candidate.competition` map.

Reports are `eligible`, `pending`, or `rejected`. Only eligible/pending cards are delivered; eligible cards rank above pending, with preferences for free registration, no presentation and estimated effort within two hours. Announcement-origin leads receive a small preference without asserting low participation. Entrant-count/prize-slot statements require evidence; award probabilities and expected winnings are never inferred. At most one pending card is sent per scan, within the existing total card cap. Undelivered `discovered` records form a durable queue. Supported event URLs generate a stable short ID, deduplicating different social posts for one event. Each scan performs at most the configured number of screens; unprocessed leads persist as `competition_pending_screen`. Atomic `competition_screening` claims prevent overlapping analyses; a ten-minute lease permits recovery after process failure. These states never authorize outreach.

Card delivery uses an atomic `discovered → telegram_sending` claim in Firestore, so overlapping scans cannot both deliver the same queued record. Expired queued contests are skipped before delivery. Model analysis reuses the existing configured fallback only for transient failures, with one request per configured model per screen.

Discovery stops starting analyses when the eight-minute soft work budget lacks sufficient headroom and reports unattempted search terms separately from search errors. Both Cloud Run and Scheduler use 600-second deadlines. Unscreened leads remain durable; an incomplete scan is not reported as comprehensive coverage.

Competition cards expose source/skip only. Callback dispatch blocks every non-skip action for this category, and `_send_approved` independently blocks it even with a forged ready draft. Owner-requested rechecks reuse the same event ID; uncertain Telegram delivery is not automatically replayed. No model output can authorize registration, payment, submission, or contact.

Source coverage is deliberately bounded: this is Threads plus configured public announcement discovery and allowlisted document review, not an exhaustive search-engine crawler. Dynamic, blocked or incomplete sources remain pending. Quote matching establishes provenance, not correctness of a model's semantic interpretation or the authority of a repost; each card links its source for owner review. ChatGPT subscription quota is used by the human's later production workflow, not by the server.

### Collaboration branch

`discovered → telegram_sending → telegram_sent → questionnaire → evaluated → draft_ready → sending → sent`

Terminal or intervention states are `skipped`, `telegram_uncertain`, `dm_unavailable`, `send_failed`, and `send_uncertain`.

The Telegram candidate-card receipt stores the returned message ID. If delivery raises after entering `telegram_sending`, the candidate moves to `telegram_uncertain` and is not automatically resent; a timeout may occur after Telegram accepted the message.

Every Telegram button is also checked against the candidate's current state and questionnaire step. Retried callbacks and buttons from old messages are rejected instead of replaying transitions or overwriting terminal states.

`generation_failed` is represented by `evaluated` plus an answer-step marker. Answers remain durable and Telegram offers an explicit drafting retry. Retrying generation never authorizes sending.

`send_uncertain` is intentionally not retried. A process can fail after Threads accepted the click but before the receipt was saved. Automatic retry could create a duplicate message.

## Trust boundaries

- Threads search uses the official API and a scoped access token.
- Telegram is owner-only. The webhook checks Telegram's secret-token header and the configured chat ID.
- Scheduler calls require a separate secret header.
- Swagger, ReDoc, and OpenAPI schema routes are disabled when `APP_ENV=production`.
- The named Firestore database `thread-opportunity` is the durable source of truth. Conditional IAM prevents the runtime from reading the project's Chronos database. Cloud Run's local filesystem is not used for state.
- Browser session material belongs in Secret Manager and must never be committed or logged.
- The UI sender is disabled by default. It requires a controlled live selector check after every material Threads UI change.
- The model can recommend and draft. It cannot approve or expand YiLi's evidence.
- Post text is an untrusted-data boundary. It is JSON-delimited and the prompt explicitly forbids following instructions found inside it.
- Gemini performs one bounded retry for transient failures and may fall back from `gemini-3.5-flash` to `gemini-3.5-flash-lite`. Both models pass through the same output validator.

## Known limitation

Threads exposes native DMs in the product, but the current public Threads API capability set does not expose a DM-send endpoint. The Playwright adapter is therefore inherently more fragile than discovery. The two components are separated so a UI change cannot break opportunity collection.
