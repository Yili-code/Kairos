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
- The named Firestore database `thread-opportunity` is the durable source of truth. Conditional IAM prevents the runtime from reading the project's Chronos database. Cloud Run's local filesystem is not used for state.
- Browser session material belongs in Secret Manager and must never be committed or logged.
- The UI sender is disabled by default. It requires a controlled live selector check after every material Threads UI change.
- The model can recommend and draft. It cannot approve or expand YiLi's evidence.
- Post text is an untrusted-data boundary. It is JSON-delimited and the prompt explicitly forbids following instructions found inside it.
- Gemini performs one bounded retry for transient failures and may fall back from `gemini-3.5-flash` to `gemini-3.5-flash-lite`. Both models pass through the same output validator.

## Known limitation

Threads exposes native DMs in the product, but the current public Threads API capability set does not expose a DM-send endpoint. The Playwright adapter is therefore inherently more fragile than discovery. The two components are separated so a UI change cannot break opportunity collection.
