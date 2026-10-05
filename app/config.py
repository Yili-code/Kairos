from __future__ import annotations

import json
import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    public_base_url: str
    telegram_bot_token: str
    telegram_owner_chat_id: int
    telegram_webhook_secret: str
    scheduler_secret: str
    threads_access_token: str
    threads_api_base: str
    threads_search_terms: tuple[str, ...]
    gemini_api_key: str
    gemini_model: str
    gemini_fallback_model: str
    google_cloud_project: str
    firestore_database: str
    firestore_collection: str
    discovery_limit_per_term: int
    telegram_max_cards_per_run: int
    shortlist_threshold: int
    dm_automation_enabled: bool
    threads_storage_state_json: str

    def validate_production(self) -> None:
        required = {
            "PUBLIC_BASE_URL": self.public_base_url,
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "TELEGRAM_OWNER_CHAT_ID": str(self.telegram_owner_chat_id) if self.telegram_owner_chat_id else "",
            "TELEGRAM_WEBHOOK_SECRET": self.telegram_webhook_secret,
            "SCHEDULER_SECRET": self.scheduler_secret,
            "THREADS_ACCESS_TOKEN": self.threads_access_token,
            "GEMINI_API_KEY": self.gemini_api_key,
            "GOOGLE_CLOUD_PROJECT": self.google_cloud_project,
        }
        missing = [name for name, value in required.items() if not value]
        if self.dm_automation_enabled and not self.threads_storage_state_json:
            missing.append("THREADS_STORAGE_STATE_JSON")
        if missing:
            raise RuntimeError("Missing production configuration: " + ", ".join(missing))

    @classmethod
    def from_env(cls, *, require_secrets: bool = True) -> "Settings":
        get = _required if require_secrets else lambda name: os.getenv(name, "").strip()
        terms = tuple(
            item.strip()
            for item in os.getenv(
                "THREADS_SEARCH_TERMS",
                (
                    "hackathon,looking for teammates,software internship,AI internship,paid project,"
                    "黑客松 組隊,徵隊友,軟體實習,AI 實習,有薪合作"
                ),
            ).split(",")
            if item.strip()
        )
        chat_id_raw = get("TELEGRAM_OWNER_CHAT_ID")
        storage_state = os.getenv("THREADS_STORAGE_STATE_JSON", "").strip()
        if storage_state:
            json.loads(storage_state)
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
            telegram_bot_token=get("TELEGRAM_BOT_TOKEN"),
            telegram_owner_chat_id=int(chat_id_raw or 0),
            telegram_webhook_secret=get("TELEGRAM_WEBHOOK_SECRET"),
            scheduler_secret=get("SCHEDULER_SECRET"),
            threads_access_token=get("THREADS_ACCESS_TOKEN"),
            threads_api_base=os.getenv("THREADS_API_BASE", "https://graph.threads.net/v1.0").rstrip("/"),
            threads_search_terms=terms,
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            gemini_fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
            firestore_database=os.getenv("FIRESTORE_DATABASE", "thread-opportunity").strip(),
            firestore_collection=os.getenv("FIRESTORE_COLLECTION", "kairos_opportunities"),
            discovery_limit_per_term=int(os.getenv("DISCOVERY_LIMIT_PER_TERM", "20")),
            telegram_max_cards_per_run=int(os.getenv("TELEGRAM_MAX_CARDS_PER_RUN", "3")),
            shortlist_threshold=int(os.getenv("SHORTLIST_THRESHOLD", "55")),
            dm_automation_enabled=_as_bool("THREADS_DM_AUTOMATION_ENABLED"),
            threads_storage_state_json=storage_state,
        )
