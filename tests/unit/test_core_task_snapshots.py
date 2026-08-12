from autotoken.core.task_snapshots import (
    compact_task_params,
    compact_task_progress,
    compact_task_result,
    task_list_snapshot,
    task_public_snapshot,
    truncate_task_list_value,
)


def test_task_public_snapshot_removes_internal_lock_flag():
    snapshot = task_public_snapshot({"task_id": "t1", "_group_lock_preacquired": True})

    assert snapshot == {"task_id": "t1"}


def test_task_list_snapshot_compacts_progress_events_and_sensitive_fields():
    snapshot = task_list_snapshot(
        {
            "task_id": "t1",
            "params": {
                "account_emails": ["a@example.com", "b@example.com"],
                "checkout_url": "https://example.invalid/secret",
                "count": 2,
            },
            "progress": {
                "stage": "running",
                "checkout_url": "https://example.invalid/secret",
                "message": "ok",
            },
            "progress_events": [{"stage": "a"}, {"stage": "b"}],
            "result": {
                "successful": 1,
                "token": "secret",
                "message": "done",
            },
        }
    )

    assert snapshot["progress_event_count"] == 2
    assert "progress_events" not in snapshot
    assert snapshot["params"] == {"count": 2, "account_emails_count": 2}
    assert snapshot["progress"] == {"stage": "running", "message": "ok"}
    assert snapshot["result"] == {"message": "done", "successful": 1}


def test_task_list_values_are_bounded_for_large_nested_data():
    value = truncate_task_list_value({"items": list(range(20)), "text": "x" * 200}, max_string=80)

    assert value["items"] == {"count": 20}
    assert len(value["text"]) == 123
    assert value["text"].endswith("...")


def test_compact_helpers_handle_invalid_inputs():
    assert compact_task_params(None) == {}
    assert compact_task_progress(None) == {}
    assert compact_task_result(["a", "b"]) == ["a", "b"]


def test_compact_task_result_keeps_refresh_quota_summary_fields():
    compact = compact_task_result(
        {
            "ok": [{"email": "ok@example.com"}],
            "exhausted": [{"email": "exhausted@example.com"}],
            "failed": [{"email": "failed@example.com"}],
            "skipped": [{"email": "skipped@example.com"}],
            "network_error": [{"email": "network@example.com"}],
            "missing": ["missing@example.com"],
            "total": 5,
            "access_token": "secret",
        }
    )

    assert compact == {
        "ok": {"count": 1},
        "exhausted": {"count": 1},
        "failed": {"count": 1},
        "skipped": {"count": 1},
        "network_error": {"count": 1},
        "missing": ["missing@example.com"],
        "total": 5,
    }
