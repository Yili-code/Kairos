from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.llm import GeminiClient
from app.models import Candidate


PROJECT = "yili-chronos-prod"
SECRET = "kairos-gemini-api-key"
DEFAULT_MODEL = "gemini-flash-latest"


async def verify(api_key: str, model: str, fallback_model: str = "") -> dict[str, object]:
    candidate = Candidate(
        id="verification-only",
        username="sample_builder",
        text="Remote hackathon team seeking a Python backend teammate. Please share relevant project experience.",
        permalink="https://example.test/verification-only",
        timestamp="",
        search_term="hackathon",
        category="hackathon",
        first_round_score=75,
        answers={
            "interest": "4",
            "capacity": "fits",
            "preferred_role": "backend",
            "motivation": "competition",
            "concern": "scope",
        },
    )
    result = await GeminiClient(api_key, model, fallback_model=fallback_model).assess_and_draft(candidate)
    return {
        "fit_score_valid": 0 <= result["fit_score"] <= 100,
        "interest_score_matches_explicit_answer": result["interest_score"] == 4,
        "language": result["language"],
        "assessment_length": len(result["assessment"]),
        "draft_length": len(result["draft_message"]),
    }


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    fallback_model = sys.argv[2] if len(sys.argv) > 2 else ""
    if not re.fullmatch(r"[a-z0-9.-]+", model):
        print("Invalid model name.")
        return 2
    if fallback_model and not re.fullmatch(r"[a-z0-9.-]+", fallback_model):
        print("Invalid fallback model name.")
        return 2
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
        result = asyncio.run(verify(api_key, model, fallback_model))
    except RuntimeError as exc:
        print(f"Kairos drafting verification failed: {exc}")
        return 3
    except Exception:
        print("Kairos drafting verification failed before validation; details were suppressed.")
        return 3
    finally:
        api_key = ""
    configured = f"{model} -> {fallback_model}" if fallback_model else model
    print(f"Kairos drafting verification succeeded with {configured}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
