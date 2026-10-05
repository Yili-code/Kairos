from __future__ import annotations

import json
import shutil
import subprocess

import httpx


PROJECT = "yili-chronos-prod"
REGION = "asia-east1"
SERVICE = "kairos"
JOB_ID = "kairos-opportunity-scan"
THREADS_SECRET = "thread-opportunity-threads-token"
SCHEDULER_SECRET = "thread-opportunity-scheduler-secret"


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
    threads_token = ""
    scheduler_secret = ""
    access_token = ""
    try:
        service_json = json.loads(gcloud_value(
            gcloud,
            (
                f"run services describe {SERVICE} --project={PROJECT} --region={REGION} "
                "--format=json"
            ),
        ))
        container = service_json["spec"]["template"]["spec"]["containers"][0]
        environment = {
            item["name"]: item.get("value", "")
            for item in container.get("env", [])
        }
        if environment.get("APP_ENV") != "production":
            print("Scheduler activation blocked: Kairos is not in production mode.")
            return 3
        service_url = str(service_json["status"]["url"]).rstrip("/")
        threads_token = gcloud_value(
            gcloud,
            f"secrets versions access latest --secret={THREADS_SECRET} --project={PROJECT}",
        )
        if not threads_token:
            print("Scheduler activation blocked: Threads token is empty.")
            return 4
        threads_token = ""
        scheduler_secret = gcloud_value(
            gcloud,
            f"secrets versions access latest --secret={SCHEDULER_SECRET} --project={PROJECT}",
        )
        access_token = gcloud_value(gcloud, "auth print-access-token")
        job_name = f"projects/{PROJECT}/locations/{REGION}/jobs/{JOB_ID}"
        body = {
            "name": job_name,
            "description": "Kairos Threads opportunity discovery at 08:00 and 20:00 Asia/Taipei",
            "schedule": "0 8,20 * * *",
            "timeZone": "Asia/Taipei",
            "httpTarget": {
                "uri": f"{service_url}/tasks/discover",
                "httpMethod": "POST",
                "headers": {"X-Scheduler-Secret": scheduler_secret},
            },
        }
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        resource_url = f"https://cloudscheduler.googleapis.com/v1/{job_name}"
        existing = httpx.get(resource_url, headers=headers, timeout=30)
        if existing.status_code == 404:
            response = httpx.post(
                f"https://cloudscheduler.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/jobs",
                headers=headers,
                json=body,
                timeout=30,
            )
        else:
            existing.raise_for_status()
            response = httpx.patch(
                resource_url,
                params={"updateMask": "description,schedule,timeZone,httpTarget"},
                headers=headers,
                json=body,
                timeout=30,
            )
        response.raise_for_status()
    except Exception:
        print("Scheduler configuration failed; credentials and provider response were suppressed.")
        return 5
    finally:
        scheduler_secret = ""
        access_token = ""
    print("Kairos scheduler configured for 08:00 and 20:00 Asia/Taipei.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
