from __future__ import annotations

import json
import shutil
import subprocess

import httpx


def main() -> int:
    gcloud = shutil.which("gcloud.cmd")
    if not gcloud:
        print("Google Cloud CLI was not found.")
        return 3
    command = (
        f'"{gcloud}" secrets versions access latest '
        "--secret=thread-opportunity-telegram-token --project=yili-chronos-prod"
    )
    try:
        token = subprocess.check_output(command, shell=True).decode("utf-8").strip()
        response = httpx.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=15,
        )
        payload = response.json()
        webhook_response = httpx.get(
            f"https://api.telegram.org/bot{token}/getWebhookInfo",
            timeout=15,
        )
        webhook_payload = webhook_response.json()
    except Exception:
        print("Telegram verification failed without exposing the token.")
        return 2
    finally:
        token = ""
    result = payload.get("result") or {}
    webhook = webhook_payload.get("result") or {}
    safe = {
        "ok": bool(payload.get("ok")),
        "bot_id": result.get("id"),
        "username": result.get("username"),
        "webhook_configured": bool(webhook.get("url")),
        "webhook_url": webhook.get("url") or "",
        "pending_update_count": webhook.get("pending_update_count", 0),
        "last_error_message": webhook.get("last_error_message") or "",
    }
    print(json.dumps(safe, ensure_ascii=True))
    return 0 if safe["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
