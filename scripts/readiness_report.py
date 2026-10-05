from __future__ import annotations

import json
import shutil
import subprocess

import httpx
from google.cloud import firestore


PROJECT = "yili-chronos-prod"
REGION = "asia-east1"
SERVICE = "kairos"
JOB_ID = "kairos-opportunity-scan"
COLLECTION = "kairos_opportunities"
DATABASE = "thread-opportunity"
TOKEN_SECRET = "thread-opportunity-telegram-token"
THREADS_SECRET = "thread-opportunity-threads-token"


def gcloud(gcloud_path: str, arguments: str) -> tuple[int, str]:
    completed = subprocess.run(
        f'"{gcloud_path}" {arguments}',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=True,
    )
    return completed.returncode, completed.stdout.decode("utf-8").strip()


def main() -> int:
    gcloud_path = shutil.which("gcloud.cmd")
    if not gcloud_path:
        print("Google Cloud CLI was not found.")
        return 2

    report: dict[str, object] = {}
    code, service_output = gcloud(
        gcloud_path,
        (
            f"run services describe {SERVICE} --project={PROJECT} --region={REGION} "
            "--format=json"
        ),
    )
    if code == 0:
        service = json.loads(service_output)
        container = service["spec"]["template"]["spec"]["containers"][0]
        environment = {
            item["name"]: item.get("value", "")
            for item in container.get("env", [])
        }
        report.update({
            "cloud_run_ready": bool(service.get("status", {}).get("latestReadyRevisionName")),
            "revision": service.get("status", {}).get("latestReadyRevisionName", ""),
            "app_env": environment.get("APP_ENV", ""),
            "public_base_url_configured": bool(environment.get("PUBLIC_BASE_URL")),
            "dm_automation_enabled": environment.get("THREADS_DM_AUTOMATION_ENABLED") == "true",
        })
    else:
        report["cloud_run_ready"] = False

    code, threads_versions = gcloud(
        gcloud_path,
        (
            f"secrets versions list {THREADS_SECRET} --project={PROJECT} "
            "--filter=state=enabled --format=value(name)"
        ),
    )
    report["threads_secret_ready"] = code == 0 and bool(threads_versions)

    code, _ = gcloud(
        gcloud_path,
        f"scheduler jobs describe {JOB_ID} --project={PROJECT} --location={REGION} --format=value(name)",
    )
    report["scheduler_configured"] = code == 0

    token = ""
    try:
        code, token = gcloud(
            gcloud_path,
            f"secrets versions access latest --secret={TOKEN_SECRET} --project={PROJECT}",
        )
        if code == 0 and token:
            response = httpx.get(
                f"https://api.telegram.org/bot{token}/getWebhookInfo",
                timeout=20,
            )
            payload = response.json().get("result", {}) if response.status_code == 200 else {}
            report["telegram_webhook_configured"] = bool(payload.get("url"))
            report["telegram_pending_updates"] = int(payload.get("pending_update_count", 0))
        else:
            report["telegram_webhook_configured"] = False
    except Exception:
        report["telegram_webhook_configured"] = False
    finally:
        token = ""

    try:
        client = firestore.Client(project=PROJECT, database=DATABASE)
        documents = list(client.collection(COLLECTION).limit(1000).stream())
        report["firestore_document_count"] = len(documents)
    except Exception:
        report["firestore_document_count"] = None

    report["production_ready"] = all([
        report.get("cloud_run_ready") is True,
        report.get("app_env") == "production",
        report.get("public_base_url_configured") is True,
        report.get("threads_secret_ready") is True,
        report.get("telegram_webhook_configured") is True,
        report.get("scheduler_configured") is True,
        report.get("dm_automation_enabled") is False,
    ])
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
