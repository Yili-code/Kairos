"""Explicit owner preferences; scenario wages are comparisons, not a personal valuation."""
COMPETITION_POLICY = {
    "version": "return-scenarios-v1",
    "min_ai_production_share": 0.5,
    "max_total_hours": None,
    "max_extra_tools_twd": None,
    "time_value_scenarios_twd_per_hour": (300, 600, 1000),
    "success_probability": "evidence_or_unknown",
}
