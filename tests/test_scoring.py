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


def test_full_time_internship_is_penalized_during_term() -> None:
    result = score_post(
        "Full-time software internship, 40 hours per week, working with Python and APIs. DM us."
    )

    assert result.category == "internship"
    assert result.score < 55
    assert any("13–16 hour" in risk for risk in result.risks)


def test_unpaid_paid_project_is_penalized() -> None:
    result = score_post(
        "Paid project style collaboration but currently unpaid. Remote Python backend work. DM me."
    )

    assert result.category == "paid_project"
    assert result.score < 55
    assert any("compensation policy" in risk for risk in result.risks)


def test_unknown_onsite_location_requires_verification() -> None:
    result = score_post(
        "AI internship, onsite five days a week in Kaohsiung. Python experience preferred. DM us."
    )

    assert result.category == "internship"
    assert any("Onsite location" in risk for risk in result.risks)


def test_upfront_payment_requirement_is_high_risk() -> None:
    result = score_post(
        "Remote hackathon team recruiting AI developers. Registration fee required before joining. DM now."
    )

    assert result.score < 55
    assert any("Upfront payment" in risk for risk in result.risks)
