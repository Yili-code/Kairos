from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from app.config import Settings, DEFAULT_COMPETITION_SEEDS
from app.competitions import CompetitionScreener
from app.announcements import AnnouncementSource
from app.fetch_policy import PublicFetcher, FirestoreFetchState
from app.dm_sender import DisabledDMSender, ThreadsBrowserSender
from app.llm import GeminiClient
from app.storage import FirestoreRepository, InMemoryRepository
from app.telegram import TelegramClient
from app.threads_client import ThreadsClient
from app.workflow import Workflow
from app.scan_runtime import ScanRunner, MemoryScanStore, FirestoreScanStore, status_text
import asyncio


def build_workflow(settings: Settings) -> Workflow:
    repository = (
        FirestoreRepository(
            settings.google_cloud_project,
            settings.firestore_database,
            settings.firestore_collection,
        )
        if settings.google_cloud_project
        else InMemoryRepository()
    )
    dm_sender = (
        ThreadsBrowserSender(settings.threads_storage_state_json)
        if settings.dm_automation_enabled
        else DisabledDMSender()
    )
    llm = GeminiClient(settings.gemini_api_key, settings.gemini_model,
                       fallback_model=settings.gemini_fallback_model)
    fetcher = PublicFetcher(FirestoreFetchState(repository.client) if isinstance(repository, FirestoreRepository) else None)
    return Workflow(
        repository=repository,
        threads=ThreadsClient(settings.threads_api_base, settings.threads_access_token),
        telegram=TelegramClient(settings.telegram_bot_token, settings.telegram_owner_chat_id),
        llm=llm,
        dm_sender=dm_sender,
        shortlist_threshold=settings.shortlist_threshold,
        per_term_limit=settings.discovery_limit_per_term,
        max_cards=settings.telegram_max_cards_per_run,
        competition_screener=CompetitionScreener(llm, settings.competition_rules_hosts, fetcher=fetcher.fresh),
        competition_screen_limit=settings.competition_screen_limit,
        announcement_source=AnnouncementSource(settings.announcement_source_urls, settings.competition_rules_hosts,
                                               seed_pages=DEFAULT_COMPETITION_SEEDS if settings.announcement_source_urls else (), fetcher=fetcher),
    )


def create_app(settings: Settings | None = None, workflow: Workflow | None = None) -> FastAPI:
    settings = settings or Settings.from_env(require_secrets=False)
    if settings.app_env == "production":
        settings.validate_production()
    active_workflow = workflow or build_workflow(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield

    expose_development_docs = settings.app_env != "production"
    api = FastAPI(
        title="Kairos",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if expose_development_docs else None,
        redoc_url="/redoc" if expose_development_docs else None,
        openapi_url="/openapi.json" if expose_development_docs else None,
    )
    api.state.settings = settings
    api.state.workflow = active_workflow
    scan_repository = getattr(active_workflow, 'repository', None)
    scan_store = (FirestoreScanStore(scan_repository.client)
                  if isinstance(scan_repository, FirestoreRepository) else MemoryScanStore())
    scan_runner = ScanRunner(scan_store, active_workflow.telegram)
    api.state.scan_runner = scan_runner

    def operational_status():
        from collections import Counter
        from app.competition_decisions import assessment_current
        from app.profile import PROFILE
        state = scan_store.status()
        if scan_repository:
            rows = scan_repository.find_by_status(['competition_pending_screen', 'competition_screening',
                'discovered', 'telegram_sending', 'telegram_uncertain', 'telegram_failed', 'telegram_sent'], limit=500)
            state['queue'] = dict(Counter(row.status for row in rows))
            state['queue_sample_limit'] = 500
            attention = [row for row in rows if row.status in {'competition_pending_screen', 'competition_screening'}
                         and row.screen_failure_streak >= 3]
            state['screen_attention_remaining'] = len(attention)
            state['screen_attention'] = [{'id': row.id, 'url': row.permalink,
                'attempts': row.screen_failure_streak, 'last_assessment': row.competition.get('checked_at'),
                'analysis_error': row.competition.get('analysis_error')} for row in attention[:10]]
            review_rows = attention + [row for row in rows if row.status == 'telegram_sent'
                and (row.competition.get('refresh_failure_streak', 0) >= 3
                     or row.competition.get('refresh_incomplete_attempts', 0) >= 3)]
            state['review_needed'] = [{'id': row.id, 'title': row.text.splitlines()[0][:80] if row.text else row.id,
                'url': row.permalink,
                'reason': '來源或模型查核未完成' if row.competition.get('analysis_error') else '必要規則或投入估算仍未確認',
                'information_gaps': row.competition.get('information_gaps', []),
                'source_statuses': sorted({item.get('status', 'unknown') for item in
                    (row.competition.get('last_refresh_diagnostics') or row.competition).get('fetch_report', [])
                    if item.get('status') != 'ok'})} for row in review_rows[:10]]
            state['card_refresh_attention_remaining'] = sum(row.status == 'telegram_sent'
                and (row.competition.get('refresh_failure_streak', 0) >= 3
                     or row.competition.get('refresh_incomplete_attempts', 0) >= 3) for row in rows)
            state['stale_sent_assessments'] = sum(row.status == 'telegram_sent' and row.category == 'ai_competition'
                and (not assessment_current(row.competition, PROFILE) or bool(row.competition.get('information_gaps'))) for row in rows)
        return state

    @api.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "environment": settings.app_env,
            "firestore_configured": bool(settings.google_cloud_project),
            "gemini_configured": bool(settings.gemini_api_key),
            "threads_search_configured": bool(settings.threads_access_token),
            "dm_automation_enabled": settings.dm_automation_enabled,
            "competition_discovery_enabled": bool(settings.competition_search_terms),
            "competition_screen_limit": settings.competition_screen_limit,
            "announcement_sources_configured": len(settings.announcement_source_urls),
            'competition_seed_sources_configured': len(DEFAULT_COMPETITION_SEEDS) if settings.announcement_source_urls else 0,
        }

    @api.post("/tasks/discover")
    async def discover(x_scheduler_secret: str | None = Header(default=None)) -> dict[str, Any]:
        if not settings.scheduler_secret or x_scheduler_secret != settings.scheduler_secret:
            raise HTTPException(status_code=403, detail="Forbidden")
        if not settings.threads_access_token:
            raise HTTPException(status_code=503, detail="Threads search is not configured")
        terms = tuple(dict.fromkeys((*settings.threads_search_terms, *settings.competition_search_terms)))
        try:
            return await scan_runner.run(lambda: active_workflow.discover(terms))
        except Exception:
            raise HTTPException(status_code=503, detail="Scan failed; inspect authenticated scan status") from None

    @api.get('/tasks/status')
    async def scan_status(x_scheduler_secret: str | None = Header(default=None)):
        if not settings.scheduler_secret or x_scheduler_secret != settings.scheduler_secret:
            raise HTTPException(status_code=403, detail='Forbidden')
        return await asyncio.to_thread(operational_status)

    @api.post("/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict[str, bool]:
        if (
            not settings.telegram_webhook_secret
            or x_telegram_bot_api_secret_token != settings.telegram_webhook_secret
        ):
            raise HTTPException(status_code=403, detail="Forbidden")
        update = await request.json()
        callback = update.get("callback_query")
        if callback:
            chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
            if int(chat_id or 0) != settings.telegram_owner_chat_id:
                raise HTTPException(status_code=403, detail="Owner only")
            await active_workflow.handle_callback(str(callback["id"]), str(callback.get("data") or ""))
            return {"ok": True}
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if int(chat_id or 0) != settings.telegram_owner_chat_id:
            raise HTTPException(status_code=403, detail="Owner only")
        text = str(message.get("text") or "").strip()
        if text:
            if text == '/status':
                await active_workflow.telegram.notify(status_text(await asyncio.to_thread(operational_status)))
                return {'ok': True}
            reply_to_text = str(((message.get("reply_to_message") or {}).get("text") or ""))
            handled = await active_workflow.handle_text(text, reply_to_text=reply_to_text)
            if not handled:
                await active_workflow.telegram.notify("No opportunity is waiting for free-text input.")
        return {"ok": True}

    return api


app = create_app()
