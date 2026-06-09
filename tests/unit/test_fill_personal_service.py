from autotoken.services import fill_personal


def test_capacity_plan_rejects_when_baseline_already_reaches_cap():
    plan = fill_personal.capacity_plan(
        requested_count=3,
        baseline_emails=["a@example.com", "b@example.com"],
        cap=2,
    )

    assert plan.rejected is True
    assert plan.should_run is False
    assert plan.target_count == 0
    assert plan.available_slots == 0


def test_capacity_plan_clamps_requested_count_to_available_slots():
    plan = fill_personal.capacity_plan(
        requested_count=4,
        baseline_emails=["A@example.com", "a@example.com", "b@example.com"],
        cap=4,
    )

    assert plan.rejected is False
    assert plan.clamped is True
    assert plan.baseline_count == 2
    assert plan.available_slots == 2
    assert plan.target_count == 2


def test_capacity_plan_allows_request_within_available_slots():
    plan = fill_personal.capacity_plan(
        requested_count=2,
        baseline_emails=["a@example.com"],
        cap=4,
    )

    assert plan.should_run is True
    assert plan.clamped is False
    assert plan.target_count == 2


def test_batch_size_respects_batch_remaining_and_available_slots():
    assert (
        fill_personal.batch_size(
            max_batch_size=4,
            remaining=10,
            baseline_emails=["a@example.com", "b@example.com"],
            cap=4,
        )
        == 2
    )
    assert (
        fill_personal.batch_size(
            max_batch_size=4,
            remaining=1,
            baseline_emails=["a@example.com"],
            cap=4,
        )
        == 1
    )
    assert (
        fill_personal.batch_size(
            max_batch_size=4,
            remaining=3,
            baseline_emails=["a@example.com", "b@example.com"],
            cap=2,
        )
        == 0
    )


def test_new_member_emails_normalizes_and_deduplicates_against_baseline():
    assert fill_personal.new_member_emails(
        ["A@example.com", "new@example.com", "NEW@example.com", ""],
        ["a@example.com"],
    ) == {"new@example.com"}


def test_outcome_with_default_status_preserves_existing_status_and_sets_missing_status():
    assert fill_personal.outcome_with_default_status({"status": "oauth_failed"}, email="user@example.com") == {
        "status": "oauth_failed"
    }
    assert fill_personal.outcome_with_default_status({"reason": "ok"}, email="user@example.com") == {
        "reason": "ok",
        "status": "success",
    }
    assert fill_personal.outcome_with_default_status({}, email=None) == {"status": "unknown_failure"}


def test_summarize_outcomes_counts_statuses_in_first_seen_order():
    summary = fill_personal.summarize_outcomes(
        [
            {"status": "success"},
            {"status": "oauth_failed"},
            {"status": "success"},
            {},
            None,
        ]
    )

    assert list(summary.items()) == [
        ("success", 2),
        ("oauth_failed", 1),
        ("unknown", 2),
    ]
