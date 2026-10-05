from __future__ import annotations

import getpass
import re
import subprocess
import sys


PROJECT = "yili-chronos-prod"
SECRET = "thread-opportunity-telegram-token"


def main() -> int:
    token = getpass.getpass("Paste the new Telegram bot token (hidden), then press Enter: ").strip()
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
        print("Token format is invalid; nothing was uploaded.", file=sys.stderr)
        return 2
    completed = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "add",
            SECRET,
            "--project",
            PROJECT,
            "--data-file=-",
        ],
        input=token.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    token = ""
    if completed.returncode != 0:
        print("Upload failed. The token was not saved.", file=sys.stderr)
        return completed.returncode
    print("Token stored in Secret Manager. You can close this terminal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
