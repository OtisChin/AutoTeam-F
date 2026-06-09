from autotoken import card_pool


def test_reserve_card_item_marks_binding_and_updates_meta(tmp_path, monkeypatch):
    pool_file = tmp_path / "card_pool.json"
    monkeypatch.setattr(card_pool, "CARD_POOL_FILE", pool_file)

    item = card_pool.add_card_item("4111111111111111", provider="demo", meta={"content": {"expiry_date": "2030/5"}})

    reserved = card_pool.reserve_card_item(
        item["id"],
        account_email="user@example.com",
        proxy_label="res-us-01",
        checkout_url="https://chatgpt.com/checkout/demo",
        task_id="task-1",
    )

    assert reserved["status"] == "binding"
    assert reserved["meta"]["bind_attempts"] == 1
    assert reserved["meta"]["last_bind_result"] == "binding"
    assert reserved["meta"]["last_account_email"] == "user@example.com"
    assert reserved["meta"]["last_proxy_label"] == "res-us-01"
    assert reserved["meta"]["last_bind_task_id"] == "task-1"


def test_finalize_card_binding_releases_reusable_failure_and_marks_success_used(tmp_path, monkeypatch):
    pool_file = tmp_path / "card_pool.json"
    monkeypatch.setattr(card_pool, "CARD_POOL_FILE", pool_file)

    item = card_pool.add_card_item("4000000000000002", provider="demo", meta={"content": {"expiry_date": "2030/5"}})
    card_pool.reserve_card_item(item["id"], account_email="user@example.com")

    released = card_pool.finalize_card_binding(
        item["id"],
        result_status="failed",
        failure_stage="open_checkout",
        message="network error",
        account_email="user@example.com",
        reusable=True,
    )

    assert released["status"] == "unused"
    assert released["meta"]["last_bind_result"] == "failed"
    assert released["meta"]["last_failure_stage"] == "open_checkout"

    card_pool.reserve_card_item(item["id"], account_email="user@example.com")
    used = card_pool.finalize_card_binding(
        item["id"],
        result_status="success",
        account_email="user@example.com",
        proxy_label="res-us-01",
        task_id="task-2",
    )

    assert used["status"] == "used"
    assert used["used_by"] == "user@example.com"
    assert used["used_at"] is not None
    assert used["meta"]["last_bind_result"] == "success"
    assert used["meta"]["last_proxy_label"] == "res-us-01"
    assert used["meta"]["last_bind_task_id"] == "task-2"


def test_stats_for_card_counts_binding_failed_and_expired(tmp_path, monkeypatch):
    pool_file = tmp_path / "card_pool.json"
    monkeypatch.setattr(card_pool, "CARD_POOL_FILE", pool_file)

    card_pool.add_card_item("4111111111111111", status="unused")
    card_pool.add_card_item("4111111111111112", status="binding")
    card_pool.add_card_item("4111111111111113", status="used")
    card_pool.add_card_item("4111111111111114", status="failed")
    card_pool.add_card_item("4111111111111115", status="expired")

    assert card_pool.stats_for("card") == {
        "total": 5,
        "unused": 1,
        "binding": 1,
        "used": 1,
        "failed": 1,
        "expired": 1,
    }
