"""Authorized production smoke: labeled owner-only Telegram test, webhook and optional discovery."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from google.cloud import firestore
from google.oauth2.credentials import Credentials

from app.models import Candidate, Status
from app.telegram import TelegramClient
from verify_competition_screening import cloud_json


def cloud_value(*arguments):
    result = subprocess.run([shutil.which("gcloud.cmd"), *arguments], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Google Cloud credential access failed")
    return result.stdout.decode().strip()


async def verify(discover: bool):
    service = cloud_json("run", "services", "describe", "kairos", "--project=yili-chronos-prod", "--region=asia-east1")
    base_url = service["status"]["url"]
    environment = {item["name"]: item for item in service["spec"]["template"]["spec"]["containers"][0]["env"]}

    def value(name):
        item = environment[name]
        if "value" in item:
            return item["value"]
        ref = item["valueFrom"]["secretKeyRef"]
        return cloud_value("secrets", "versions", "access", ref["key"], "--secret=" + ref["name"], "--project=yili-chronos-prod")

    report = {"revision": service["status"]["latestReadyRevisionName"]}
    telegram = TelegramClient(value("TELEGRAM_BOT_TOKEN"), int(value("TELEGRAM_OWNER_CHAT_ID")))
    client = firestore.Client(project="yili-chronos-prod", database=value("FIRESTORE_DATABASE"),
                              credentials=Credentials(cloud_value("auth", "print-access-token")))
    collection = client.collection(value("FIRESTORE_COLLECTION"))
    async with httpx.AsyncClient(timeout=180) as http:
        health = await http.get(base_url + "/health")
        health.raise_for_status()
        report["competition_discovery_enabled"] = health.json().get("competition_discovery_enabled") is True
        report["dm_automation_disabled"] = health.json().get("dm_automation_enabled") is False
        forbidden = await http.post(base_url + "/tasks/discover", headers={"X-Scheduler-Secret": "invalid-smoke-test"})
        report["unauthenticated_discovery_rejected"] = forbidden.status_code == 403
        await telegram.notify("[E2E TEST] Kairos 競賽功能正式環境驗證：接下來會有一張清楚標示的測試卡，以及一場真實舊競賽的規則核對結果。這些訊息不是推薦，不會報名、付費、交件或對外聯繫。")

        candidate = Candidate(
            "e2e-contest-" + uuid.uuid4().hex[:12], "test", "[E2E TEST] 版面與投遞測試，並非真實競賽。可按略過。",
            base_url + "/health", "", "E2E TEST", category="ai_competition", status=Status.TELEGRAM_SENDING,
            competition={"decision": "pending", "facts": {}, "sources": [], "estimate": {},
                         "blockers": ["測試資料：不代表有符合條件的競賽"]},
        )
        reference = collection.document(candidate.id)
        reference.create(candidate.to_dict())
        try:
            candidate.telegram_message_id = await telegram.send_candidate(candidate)
        except RuntimeError:
            reference.update({"status": Status.TELEGRAM_UNCERTAIN})
            raise
        reference.update({"status": Status.TELEGRAM_SENT, "telegram_message_id": candidate.telegram_message_id})
        report["labeled_test_card_accepted_by_telegram"] = candidate.telegram_message_id > 0
        report["test_card_persisted"] = reference.get().to_dict()["status"] == Status.TELEGRAM_SENT

        rules_url = "https://hackthenet2026.devpost.com/rules"
        response = await http.post(base_url + "/telegram/webhook", headers={
            "X-Telegram-Bot-Api-Secret-Token": value("TELEGRAM_WEBHOOK_SECRET"),
        }, json={"update_id": int(time.time()), "message": {
            "chat": {"id": telegram.owner_chat_id}, "text": "/competition " + rules_url,
        }})
        report["production_command_webhook_ok"] = response.status_code == 200
        record = collection.document("contest-" + hashlib.sha256(rules_url.encode()).hexdigest()[:24]).get()
        data = record.to_dict() if record.exists else {}
        report["production_command_record_persisted"] = record.exists
        report["production_command_decision"] = data.get("competition", {}).get("decision")
        report["production_command_has_no_outreach_approval"] = not any(
            data.get(name) for name in ("approval_hash", "send_attempt_id", "sent_at")
        )
        if discover:
            response = await http.post(base_url + "/tasks/discover", headers={"X-Scheduler-Secret": value("SCHEDULER_SECRET")})
            report["production_discovery_http_status"] = response.status_code
            if response.status_code == 200:
                report["production_discovery"] = response.json()
    print(json.dumps(report, ensure_ascii=False))
    return 0 if all(report.get(key) is True for key in (
        "competition_discovery_enabled", "dm_automation_disabled", "unauthenticated_discovery_rejected",
        "labeled_test_card_accepted_by_telegram", "test_card_persisted", "production_command_webhook_ok",
        "production_command_record_persisted", "production_command_has_no_outreach_approval",
    )) and (not discover or report.get("production_discovery_http_status") == 200) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discover", action="store_true", help="Also run a real production scan; may deliver owner cards")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(verify(args.discover)))
    except Exception as exc:
        print(json.dumps({"verification_failed": type(exc).__name__}))
        sys.exit(1)
