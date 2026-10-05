from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


PROJECT = "yili-chronos-prod"
SECRET = "kairos-gemini-api-key"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def main() -> int:
    entries: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        entries[key.strip()] = value.strip()

    api_key = entries.get("GEMINI_API_KEY", "")
    if len(api_key) < 20 or any(character.isspace() for character in api_key):
        print("The local Gemini API key is missing or has an invalid format.")
        return 2

    gcloud = shutil.which("gcloud.cmd")
    if not gcloud:
        print("Google Cloud CLI was not found.")
        return 3

    command = (
        f'"{gcloud}" secrets versions add {SECRET} '
        f'--project={PROJECT} --data-file=-'
    )
    completed = subprocess.run(
        command,
        input=api_key.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=True,
    )
    api_key = ""
    if completed.returncode != 0:
        print("Secret Manager upload failed; no credential was printed.")
        return completed.returncode

    print("Gemini API key stored as the latest Secret Manager version.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
