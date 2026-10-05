from app.profile import PROFILE


def test_profile_contains_latest_confirmed_constraints() -> None:
    assert PROFILE["english"]["score"] == 805
    assert PROFILE["education"]["expected_graduation"] == "2028-06"
    assert PROFILE["term_hours_per_week"] == {"min": 13, "max": 16}
    assert PROFILE["break_availability"]["hours_per_week"] == "requires confirmation"
    assert "break_hours_per_week" not in PROFILE
    assert PROFILE["unpaid_trial"]["commercial_use_allowed"] is False
    assert PROFILE["cross_timezone_meetings_ok"] is True
    assert any(item["name"] == "Programming competitions" for item in PROFILE["evidence"])
