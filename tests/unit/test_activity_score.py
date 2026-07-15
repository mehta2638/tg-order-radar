from app.services.activity import (
    ActivityMetrics,
    activity_poll_mode,
    activity_status,
    calculate_activity_score,
)


def test_calculate_activity_score_matches_spec_example() -> None:
    metrics = ActivityMetrics(
        msg_count_7d=180,
        order_candidates_7d=35,
        hours_since_last=2,
        active_days_7d=7,
        relevant_orders_7d=20,
        spam_7d=3,
        dup_7d=0,
    )

    assert calculate_activity_score(metrics) == 85
    assert activity_status(85) == "high"
    assert activity_poll_mode(85, "channel") == "realtime"


def test_calculate_activity_score_inactive_source() -> None:
    metrics = ActivityMetrics(
        msg_count_7d=8,
        order_candidates_7d=1,
        hours_since_last=200,
        active_days_7d=2,
        relevant_orders_7d=0,
        spam_7d=1,
        dup_7d=0,
    )

    assert calculate_activity_score(metrics) == 4
    assert activity_status(4) == "inactive"
    assert activity_poll_mode(4, "megagroup") == "poll"


def test_activity_status_thresholds() -> None:
    assert activity_status(19) == "inactive"
    assert activity_status(20) == "low"
    assert activity_status(50) == "active"
    assert activity_status(75) == "high"
    assert activity_poll_mode(50, "megagroup") == "realtime"
    assert activity_poll_mode(50, "channel") == "poll"
