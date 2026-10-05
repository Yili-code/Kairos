from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


PROJECT = "yili-chronos-prod"
SECRET = "thread-opportunity-telegram-token"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def main() -> int:
    entries: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        entries[key.strip()] = value.strip()
    token = entries.get("TELEGRAM_BOT_TOKEN", "")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
        print("The local token is missing or has an invalid format.")
        return 2
    gcloud = shutil.which("gcloud.cmd")
    if not gcloud:
        print("Google Cloud CLI was not found.")
        return 3
    command = (
        f'"{gcloud}" secrets versions add {SECRET} '
        f'--project {PROJECT} --data-file=-'
    )
    completed = subprocess.run(
        command,
        input=token.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=True,
    )
    token = ""
    if completed.returncode != 0:
        print("Secret Manager upload failed; the local file was left unchanged.")
        return completed.returncode
    print("Telegram token stored in Secret Manager.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
