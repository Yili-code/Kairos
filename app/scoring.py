from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import Candidate


CATEGORY_PATTERNS = {
    "hackathon": ("hackathon", "hack day", "team member", "teammate", "組隊", "黑客松"),
    "internship": ("intern", "internship", "實習", "實習生"),
    "paid_project": ("paid project", "freelance", "contract", "commission", "接案", "有薪合作"),
}

SKILL_TERMS = (
    "python",
    "fastapi",
    "ai",
    "llm",
    "gemini",
    "telegram",
    "cloud run",
    "backend",
    "api",
    "docker",
    "firestore",
)

RED_FLAGS = (
    "unpaid internship",
    "work for exposure",
    "equity only",
    "commission only",
    "guaranteed income",
    "先繳費",
    "免費實習",
    "無薪實習",
)


@dataclass(frozen=True)
class ScoreResult:
    category: str
    score: int
    reasons: list[str]
    risks: list[str]


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def score_post(text: str) -> ScoreResult:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    category = "other"
    base = 5
    for name, patterns in CATEGORY_PATTERNS.items():
        if _contains(normalized, patterns):
            category = name
            base = {"hackathon": 35, "internship": 30, "paid_project": 25}[name]
            break

    reasons: list[str] = []
    risks: list[str] = []
    score = base
    if category != "other":
        reasons.append(f"Matches {category.replace('_', ' ')} priority")

    matched_skills = [term for term in SKILL_TERMS if term in normalized]
    if matched_skills:
        score += min(24, len(matched_skills) * 6)
        reasons.append("Relevant stack: " + ", ".join(matched_skills[:4]))

    if _contains(normalized, ("remote", "hybrid", "遠端", "台北", "taipei", "keelung", "基隆")):
        score += 12
        reasons.append("Location or remote preference fits")

    if _contains(normalized, ("competition", "demo day", "prize", "award", "競賽", "決賽", "獎金")):
        score += 12
        reasons.append("Competition or outcome value")

    if _contains(normalized, ("paid", "salary", "stipend", "compensation", "有薪", "薪資", "津貼")):
        score += 10
        reasons.append("Compensation is mentioned")

    if _contains(normalized, ("student", "university", "undergraduate", "學生", "大學生")):
        score += 6
        reasons.append("Student profile is relevant")

    if len(normalized) >= 180:
        score += 4
        reasons.append("Post provides meaningful detail")

    for flag in RED_FLAGS:
        if flag in normalized:
            score -= 35
            risks.append(f"Red flag: {flag}")

    if category == "other":
        risks.append("Opportunity type is unclear")
    if not re.search(r"(?:https?://|@\w+|dm\b|message\b|私訊|聯絡)", normalized):
        risks.append("No explicit next step or contact path")

    return ScoreResult(category, max(0, min(100, score)), reasons, risks)


def apply_score(candidate: Candidate) -> Candidate:
    result = score_post(candidate.text)
    candidate.category = result.category
    candidate.first_round_score = result.score
    candidate.reasons = result.reasons
    candidate.risks = result.risks
    return candidate
