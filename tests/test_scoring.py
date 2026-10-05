from app.scoring import score_post


def test_hackathon_remote_ai_post_scores_high() -> None:
    result = score_post(
        "Looking for a student teammate for a remote AI hackathon. "
        "Python backend experience is useful. DM me to join the competition."
    )
    assert result.category == "hackathon"
    assert result.score >= 55
    assert any("Relevant stack" in reason for reason in result.reasons)


def test_unpaid_internship_is_penalized() -> None:
    result = score_post("Unpaid internship. Build our commercial backend for exposure. DM us.")
    assert result.category == "internship"
    assert result.score < 55
    assert result.risks


def test_unrelated_post_is_not_shortlisted() -> None:
    result = score_post("A nice day at the beach")
    assert result.category == "other"
    assert result.score < 55
