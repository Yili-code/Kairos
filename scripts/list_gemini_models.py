from __future__ import annotations

import shutil
import subprocess

import httpx


PROJECT = "yili-chronos-prod"
SECRET = "kairos-gemini-api-key"


def main() -> int:
    gcloud = shutil.which("gcloud.cmd")
    if not gcloud:
        print("Google Cloud CLI was not found.")
        return 2

    accessed = subprocess.run(
        (
            f'"{gcloud}" secrets versions access latest '
            f'--secret={SECRET} --project={PROJECT}'
        ),
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
        response = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
            timeout=30,
        )
    except httpx.HTTPError:
        print("Gemini model discovery could not reach the provider.")
        return 3
    finally:
        api_key = ""

    if response.status_code != 200:
        print(f"Gemini model discovery failed with HTTP {response.status_code}; response body was suppressed.")
        return 4

    models = []
    for model in response.json().get("models", []):
        methods = model.get("supportedGenerationMethods", [])
        name = str(model.get("name", "")).removeprefix("models/")
        if "generateContent" in methods and "flash" in name.lower():
            models.append(name)
    if not models:
        print("No Flash generateContent model was returned for this key.")
        return 5
    print("Available Flash models:")
    for name in sorted(models):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
