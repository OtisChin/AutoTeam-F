from autotoken.services import paypal_pending_retry


def test_append_unique_and_remove_email_normalize_values():
    emails = []

    assert paypal_pending_retry.append_unique_email(emails, " USER@example.com ") == "user@example.com"
    assert paypal_pending_retry.append_unique_email(emails, "user@example.com") == "user@example.com"
    assert emails == ["user@example.com"]

    assert paypal_pending_retry.remove_email(emails, "USER@example.com") == "user@example.com"
    assert emails == []


def test_queue_and_remove_pending_retry_mutate_all_queues():
    pending_emails = []
    pending_queue = []
    candidate_queue = []

    progress = paypal_pending_retry.queue_pending_retry(
        pending_retry_emails=pending_emails,
        pending_retry_queue=pending_queue,
        candidate_queue=candidate_queue,
        candidate_email=" USER@example.com ",
        reason="paypal_return_timeout",
        result_payload={"failure_stage": "paypal_return_timeout"},
        retry_round=1,
        current_index=2,
        total_count=3,
        max_retry_rounds=2,
        source_stage=lambda result, reason: result.get("failure_stage") or reason,
    )

    assert pending_emails == ["user@example.com"]
    assert pending_queue == [
        {
            "email": "user@example.com",
            "reason": "paypal_return_timeout",
            "retry_round": 1,
            "current": 2,
            "total": 3,
            "result": {"failure_stage": "paypal_return_timeout"},
        }
    ]
    assert candidate_queue == [{"email": "user@example.com", "current": 2, "retry_round": 1}]
    assert progress["stage"] == "paypal_pending_retry_queued"
    assert progress["pending_retry"] == 1
    assert progress["source_stage"] == "paypal_return_timeout"

    removed = paypal_pending_retry.remove_pending_retry(
        candidate_email="USER@example.com",
        pending_retry_emails=pending_emails,
        pending_retry_queue=pending_queue,
    )

    assert removed == "user@example.com"
    assert pending_emails == []
    assert pending_queue == []


def test_pending_retry_wait_seconds_and_progress_payloads():
    waited = set()

    assert paypal_pending_retry.pending_retry_wait_seconds(1, waited, [60.0, 120.0]) == 60.0
    assert paypal_pending_retry.pending_retry_wait_seconds(1, waited, [60.0, 120.0]) is None
    assert paypal_pending_retry.pending_retry_wait_seconds(2, waited, [60.0, 120.0]) == 120.0
    assert paypal_pending_retry.pending_retry_wait_seconds(3, set()) == 120.0
    assert paypal_pending_retry.pending_retry_wait_seconds("bad", set(), [5.0, 10.0]) == 5.0
    assert paypal_pending_retry.pending_retry_wait_seconds(1, set(), []) == 0.0
    assert paypal_pending_retry.pending_retry_wait_seconds(0, set(), [5.0]) is None

    wait_progress = paypal_pending_retry.pending_retry_wait_progress(
        retry_round=2,
        max_retry_rounds=3,
        pending_count=4,
        wait_seconds=120.0,
    )
    started_progress = paypal_pending_retry.pending_retry_started_progress(
        retry_round=2,
        max_retry_rounds=3,
        pending_count=4,
        concurrency=2,
    )

    assert wait_progress == {
        "stage": "paypal_pending_retry_wait",
        "retry_round": 2,
        "max_retry_rounds": 3,
        "pending_retry": 4,
        "wait_seconds": 120.0,
        "message": "PayPal 待重试第 2/3 轮将在 120s 后开始",
    }
    assert started_progress["stage"] == "paypal_pending_retry_started"
    assert started_progress["concurrency"] == 2
    assert started_progress["message"] == "开始并发 PayPal 待重试第 2/3 轮，共 4 个账号，并发 2"


def test_pending_retry_queued_progress_can_preserve_legacy_shape_without_source_stage():
    progress = paypal_pending_retry.pending_retry_queued_progress(
        candidate_email="user@example.com",
        current_index=1,
        total_count=2,
        pending_retry_count=None,
        retry_round=1,
        max_retry_rounds=2,
        reason="needs_review",
        result_payload={"failure_stage": "paypal_authorize"},
        source_stage=lambda _result, _reason: "paypal_authorize",
        message="queued",
        level="warn",
        include_source_stage=False,
    )
    default_message = paypal_pending_retry.pending_retry_queued_progress(
        candidate_email="fallback@example.com",
        current_index=1,
        total_count=2,
        pending_retry_count=1,
        retry_round=1,
        max_retry_rounds=2,
        reason="needs_review",
        result_payload={"failure_stage": "paypal_authorize"},
        source_stage=lambda _result, _reason: "paypal_authorize",
    )

    assert "pending_retry" not in progress
    assert "source_stage" not in progress
    assert progress["level"] == "warn"
    assert progress["message"] == "queued"
    assert default_message["message"] == "PayPal 账号进入待重试池: fallback@example.com"


def test_parallel_queued_progress_builds_round_specific_shapes():
    first_round = paypal_pending_retry.parallel_first_round_queued_progress(
        candidate_email="user@example.com",
        current_index=1,
        total_count=3,
        retry_round=1,
        max_retry_rounds=2,
        reason="paypal_return_timeout",
        result_payload={"failure_stage": "paypal_return_timeout"},
        source_stage=lambda result, reason: result.get("failure_stage") or reason,
    )
    next_round = paypal_pending_retry.parallel_next_round_queued_progress(
        candidate_email="user@example.com",
        current_index=1,
        total_count=3,
        pending_retry_count=2,
        source_retry_round=1,
        retry_round=2,
        max_retry_rounds=2,
        reason="paypal_return_timeout",
        result_payload={"failure_stage": "paypal_return_timeout"},
        source_stage=lambda result, reason: result.get("failure_stage") or reason,
    )

    assert first_round["message"] == "PayPal 并发首轮失败，已加入待重试池: user@example.com"
    assert first_round["level"] == "warn"
    assert "pending_retry" not in first_round
    assert "source_stage" not in first_round
    assert next_round["message"] == "PayPal 待重试第 1/2 轮失败，已加入下一轮待重试池: user@example.com"
    assert next_round["pending_retry"] == 2
    assert next_round["source_stage"] == "paypal_return_timeout"


def test_candidate_retry_reason_requires_available_phone_for_phone_pool_failures():
    phones = [{"phone_number": "+1 835 288 0840"}]

    assert (
        paypal_pending_retry.candidate_retry_reason(
            {"failure_stage": "paypal_phone_rejected"},
            retry_reason=lambda _result: "paypal_phone_rejected",
            phone_accounts=phones,
            invalid_phone_keys={"8352880840"},
            phone_available=lambda phone, invalid: (
                phone["phone_number"].replace(" ", "").replace("+1", "") not in invalid
            ),
        )
        == ""
    )
    assert (
        paypal_pending_retry.candidate_retry_reason(
            {"failure_stage": "paypal_return_timeout"},
            retry_reason=lambda _result: "paypal_return_timeout",
            phone_accounts=[],
            invalid_phone_keys=set(),
            phone_available=lambda _phone, _invalid: False,
        )
        == "paypal_return_timeout"
    )
