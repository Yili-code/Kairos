from __future__ import annotations

import shutil
import subprocess


PROJECT = "yili-chronos-prod"
OLD_KEY = "projects/871491483193/locations/global/keys/4f237ffc-bacc-4e2c-b652-53d2ba07ffc4"
SECRET = "kairos-gemini-api-key"
OLD_SECRET_VERSION = "1"


def run(gcloud: str, arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        f'"{gcloud}" {arguments}',
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

    deleted = run(
        gcloud,
        f"services api-keys delete {OLD_KEY} --project={PROJECT} --quiet",
    )
    if deleted.returncode != 0:
        print("Old paid-project API key deletion failed; output was suppressed.")
        return deleted.returncode

    destroyed = run(
        gcloud,
        (
            f"secrets versions destroy {OLD_SECRET_VERSION} "
            f"--secret={SECRET} --project={PROJECT} --quiet"
        ),
    )
    if destroyed.returncode != 0:
        print("Old API key was deleted, but Secret Manager version 1 destruction failed.")
        return destroyed.returncode

    print("Old paid-project API key deleted and Secret Manager version 1 destroyed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
