from __future__ import annotations

import json
import shutil
import subprocess


PROJECT = "yili-chronos-prod"
SECRET = "kairos-gemini-api-key"
DISPLAY_NAME = "Kairos Gemini"
API_SERVICE = "generativelanguage.googleapis.com"


def run_gcloud(gcloud: str, arguments: str, *, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    command = f'"{gcloud}" {arguments}'
    return subprocess.run(
        command,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=True,
    )


def main() -> int:
    gcloud = shutil.which("gcloud.cmd")
    if not gcloud:
        print("Google Cloud CLI was not found.")
        return 2

    created = run_gcloud(
        gcloud,
        (
            "services api-keys create "
            f"--project={PROJECT} "
            f'--display-name="{DISPLAY_NAME}" '
            f"--api-target=service={API_SERVICE} "
            "--format=json"
        ),
    )
    if created.returncode != 0:
        print("Gemini API key creation failed. No credential was printed.")
        return created.returncode

    try:
        payload = json.loads(created.stdout.decode("utf-8"))
        key_name = payload["response"]["name"]
        key_string = payload["response"]["keyString"]
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        print("Gemini API key creation returned an unexpected response.")
        return 3

    stored = run_gcloud(
        gcloud,
        f"secrets versions add {SECRET} --project={PROJECT} --data-file=-",
        stdin=key_string.encode("utf-8"),
    )
    key_string = ""
    if stored.returncode != 0:
        run_gcloud(
            gcloud,
            f"services api-keys delete {key_name} --project={PROJECT} --quiet",
        )
        print("Secret Manager upload failed; the newly created key was deleted.")
        return stored.returncode

    print("Restricted Gemini API key created and stored in Secret Manager.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
