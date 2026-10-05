from __future__ import annotations

import shutil
import subprocess

import httpx


PROJECT = "yili-chronos-prod"
REGION = "asia-east1"
SERVICE = "kairos"
TOKEN_SECRET = "thread-opportunity-telegram-token"
WEBHOOK_SECRET = "thread-opportunity-webhook-secret"


def gcloud_value(gcloud: str, arguments: str) -> str:
    completed = subprocess.run(
        f'"{gcloud}" {arguments}',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("A required Google Cloud lookup failed")
    return completed.stdout.decode("utf-8").strip()


def main() -> int:
    gcloud = shutil.which("gcloud.cmd")
    if not gcloud:
        print("Google Cloud CLI was not found.")
        return 2
    token = ""
    secret_token = ""
    try:
        token = gcloud_value(
            gcloud,
            f"secrets versions access latest --secret={TOKEN_SECRET} --project={PROJECT}",
        )
        secret_token = gcloud_value(
            gcloud,
            f"secrets versions access latest --secret={WEBHOOK_SECRET} --project={PROJECT}",
        )
        service_url = gcloud_value(
            gcloud,
            (
                f"run services describe {SERVICE} --project={PROJECT} --region={REGION} "
                "--format=value(status.url)"
            ),
        ).rstrip("/")
        webhook_url = f"{service_url}/telegram/webhook"
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={
                "url": webhook_url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": False,
            },
            timeout=30,
        )
        payload = response.json()
    except Exception:
        print("Telegram webhook configuration failed; credentials and provider response were suppressed.")
        return 3
    finally:
        token = ""
        secret_token = ""
    if response.status_code != 200 or not payload.get("ok"):
        print(f"Telegram webhook configuration failed with HTTP {response.status_code}.")
        return 4
    print(f"Telegram webhook configured for {webhook_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
