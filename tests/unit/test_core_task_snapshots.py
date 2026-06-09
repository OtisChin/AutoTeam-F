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
