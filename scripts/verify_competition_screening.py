"""Read-only live rules/model check; no Firestore writes or Telegram delivery."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.competitions import CompetitionScreener, allowed_url
from app.llm import GeminiClient
from app.models import Candidate


def cloud_json(*arguments):
    result = subprocess.run([shutil.which("gcloud.cmd"), *arguments, "--format=json"], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Google Cloud metadata access failed")
    return json.loads(result.stdout)


async def verify(url: str):
    hosts = ("devpost.com", "kaggle.com", "bhuntr.com")
    if not allowed_url(url, hosts):
        raise RuntimeError("Unsupported rules URL")
    service = cloud_json("run", "services", "describe", "kairos", "--project=yili-chronos-prod", "--region=asia-east1")
    environment = {item["name"]: item for item in service["spec"]["template"]["spec"]["containers"][0]["env"]}
    ref = environment["GEMINI_API_KEY"]["valueFrom"]["secretKeyRef"]
    result = subprocess.run([
        shutil.which("gcloud.cmd"), "secrets", "versions", "access", ref["key"],
        "--secret=" + ref["name"], "--project=yili-chronos-prod",
    ], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("Gemini secret access failed")
    client = GeminiClient(result.stdout.decode().strip(), environment["GEMINI_MODEL"]["value"],
                          fallback_model=environment.get("GEMINI_FALLBACK_MODEL", {}).get("value", ""))
    screener = CompetitionScreener(client, hosts)
    candidate = Candidate("read-only-verification", "organizer", url, url, "", "verification")
    await screener.screen(candidate)
    report = candidate.competition
    if report["sources"] and not report["facts"]:
        sources = await screener.sources(candidate.text)
        try:
            await client.screen_competition(candidate, sources)
        except RuntimeError as exc:
            print(json.dumps({"model_diagnostic": str(exc)}, ensure_ascii=False))
    print(json.dumps({
        "rules_pages_fetched": len(report["sources"]), "decision": report["decision"],
        "facts_with_evidence": sum(bool(f.get("quote")) for f in report["facts"].values()),
        "model_result_validated": bool(report["facts"]), "blockers": report["blockers"],
        "estimated_total_hours": report["estimate"].get("total_hours"),
        "estimated_ai_share": report["estimate"].get("ai_share"),
    }, ensure_ascii=False))
    if not report["sources"] or not report["facts"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(verify(args.url)))
    except Exception as exc:
        # Never print HTTP transport exception details; requests contain credentials.
        print(json.dumps({"verification_failed": type(exc).__name__}))
        sys.exit(1)
