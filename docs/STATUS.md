# Kairos production status

Last verified: 2026-10-05 (Asia/Taipei)

## Live evidence

- Cloud Run revision `kairos-00003-t4z` serves 100% of traffic and `/health` returns `ok`.
- Firestore database `thread-opportunity` is reachable and currently contains zero opportunity documents.
- The Free Tier Gemini key successfully produced a schema-valid Kairos assessment and draft through the `gemini-3.5-flash` to `gemini-3.5-flash-lite` fallback chain.
- Thirty local tests pass, including direct FastAPI route-boundary checks and uncertain Telegram delivery coverage.
- `PUBLIC_BASE_URL` is configured.
- DM automation remains disabled.

## Activation gates

1. The Threads access-token secret has no enabled version. Discovery cannot run.
2. The Telegram bot is valid, but no webhook is registered. Confirm that the previously exposed token was revoked before registration.
3. No Cloud Scheduler job exists. The configuration helper refuses activation until Threads is configured and `APP_ENV=production`.
4. The Threads browser-DM adapter has not passed a controlled test-account selector check. Do not enable it before that check.

## Evidence boundary

Cloud Run health proves process readiness only. It does not prove live Threads discovery, Telegram interaction, or private-message delivery. Production readiness remains false until the activation gates above are completed and one controlled end-to-end candidate reaches Telegram without sending a DM.
