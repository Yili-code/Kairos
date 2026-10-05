from __future__ import annotations

import shutil
import subprocess

import httpx


PROJECT = "yili-chronos-prod"
SECRET = "kairos-gemini-api-key"
MODEL = "gemini-flash-latest"


def main() -> int:
    gcloud = shutil.which("gcloud.cmd")
    if not gcloud:
        print("Google Cloud CLI was not found.")
        return 2

    command = (
        f'"{gcloud}" secrets versions access latest '
        f'--secret={SECRET} --project={PROJECT}'
    )
    accessed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=True,
    )
    if accessed.returncode != 0:
        print("Secret Manager access failed; no credential was printed.")
        return accessed.returncode

    api_key = accessed.stdout.decode("utf-8").strip()
    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            headers={"x-goog-api-key": api_key},
            json={
                "contents": [{"parts": [{"text": "Reply with exactly: OK"}]}],
                "generationConfig": {"maxOutputTokens": 8, "temperature": 0},
            },
            timeout=30,
        )
    except httpx.HTTPError:
        print("Gemini API probe could not reach the provider.")
        return 3
    finally:
        api_key = ""

    if response.status_code != 200:
        print(f"Gemini API probe failed with HTTP {response.status_code}; response body was suppressed.")
        return 4

    print(f"Gemini API probe succeeded with {MODEL}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
