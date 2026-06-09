import hashlib
import json

from autotoken.services import gopay_pro_pool


def test_pool_line_phone_and_phone_key_normalize_number_lines():
    assert gopay_pro_pool.pool_line_phone("+628100000000----token----pin") == "+628100000000"
    assert gopay_pro_pool.pool_line_phone("  +628100000001  ") == "+628100000001"
    assert gopay_pro_pool.phone_key("+62 810-000-0000") == "628100000000"
    assert gopay_pro_pool.local_phone("+628100000000") == "8100000000"
    assert gopay_pro_pool.local_phone("628100000001") == "8100000001"


def test_pool_cooldown_original_line_accepts_autotoken_comment_format():
    line = "# autotoken-cooldown until=1770000000 reason=ratelimited +628100000000----token"

    assert gopay_pro_pool.pool_cooldown_original_line(line) == (1770000000, "+628100000000----token")
    assert gopay_pro_pool.pool_cooldown_original_line("+628100000000----token") == (0, "")
    assert gopay_pro_pool.pool_cooldown_original_line("# autotoken-cooldown invalid") == (0, "")


def test_token_fingerprint_normalizes_bearer_and_json_token_values():
    token = "access-token-1"
    expected = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]

    assert gopay_pro_pool.token_fingerprint(f"Bearer {token},") == expected
    assert gopay_pro_pool.token_fingerprint(json.dumps({"accessToken": token})) == expected
    assert gopay_pro_pool.token_fingerprint("") == ""


def test_normalize_access_token_preserves_trailing_s_while_trimming_wrappers():
    assert gopay_pro_pool.normalize_access_token("Bearer new-access,") == "new-access"
    assert gopay_pro_pool.normalize_access_token("'token-ends'") == "token-ends"
    assert gopay_pro_pool.normalize_access_token(" token-with-space \n") == "token-with-space"


def test_build_token_map_payload_filters_invalid_items_and_never_stores_raw_token():
    token = "access-token-1"
    fingerprint = gopay_pro_pool.token_fingerprint(token)

    payload = gopay_pro_pool.build_token_map_payload(
        [
            {"email": " user@example.com ", "access_token": token, "account_id": " account-1 ", "auth_file": " a.json "},
            {"email": "", "access_token": "missing-email"},
            {"email": "missing-token@example.com", "access_token": ""},
        ],
        updated_at=123,
    )

    assert payload == {
        "version": 1,
        "updated_at": 123,
        "tokens": {
            fingerprint: {
                "email": "user@example.com",
                "account_id": "account-1",
                "auth_file": "a.json",
            }
        },
    }
    assert token not in json.dumps(payload)


def test_slot_email_from_token_map_resolves_by_key_or_slot_id():
    token = "access-token-1"
    fingerprint = gopay_pro_pool.token_fingerprint(token)
    token_map = {"tokens": {fingerprint: {"email": "user@example.com"}}}

    assert (
        gopay_pro_pool.slot_email_from_token_map(
            {"slots": {"slot-01": {"access_token": token}}},
            token_map,
            "slot-01",
        )
        == "user@example.com"
    )
    assert (
        gopay_pro_pool.slot_email_from_token_map(
            {"slots": {"old-key": {"id": "slot-02", "accessToken": token}}},
            token_map,
            "slot-02",
        )
        == "user@example.com"
    )
    assert gopay_pro_pool.slot_email_from_token_map({"slots": {}}, token_map, "slot-03") == ""


def test_pool_line_access_token_reads_plain_and_json_token_lines():
    assert gopay_pro_pool.pool_line_access_token("Bearer access-token-1;") == "access-token-1"
    assert gopay_pro_pool.pool_line_access_token(json.dumps({"access_token": "token-a"})) == "token-a"
    assert gopay_pro_pool.pool_line_access_token(json.dumps({"accessToken": "token-b"})) == "token-b"
    assert gopay_pro_pool.pool_line_access_token(json.dumps({"tokens": {"access_token": "token-c"}})) == "token-c"
    assert gopay_pro_pool.pool_line_access_token("# disabled token") == ""
    assert gopay_pro_pool.pool_line_access_token("") == ""


def test_slot_pick_score_prefers_expected_slot_refresh_token_state_and_update_time():
    assert gopay_pro_pool.slot_pick_score(
        "slot-01",
        {"refresh_token": "refresh", "state": "WALLET_READY", "updated_at": 10},
        "slot-01",
    ) == (1, 1, 90, 10)
    assert gopay_pro_pool.slot_pick_score(
        "slot-02",
        {"state": "FAILED", "updated_at": "not-int"},
        "slot-01",
    ) == (0, 0, 10, 0)


def test_mask_phone_and_slot_index_preserve_existing_shapes():
    assert gopay_pro_pool.mask_phone("+628100000000") == "+6281****000"
    assert gopay_pro_pool.mask_phone("1234567") == "1234567"
    assert gopay_pro_pool.slot_index({"id": "slot-13"}) == 13
    assert gopay_pro_pool.slot_index("slot-02") == 2
    assert gopay_pro_pool.slot_index("slot-x") == 0


def test_normalize_slots_for_number_lines_reorders_slots_by_active_number_pool():
    slots = {
        "old-2": {
            "id": "slot-99",
            "state": "FAILED",
            "card": "+628100000002----old",
            "full_phone": "+628100000002",
            "updated_at": 3,
        },
        "old-1": {
            "id": "slot-03",
            "state": "WALLET_READY",
            "refresh_token": "refresh",
            "full_phone": "+628100000001",
            "updated_at": 10,
        },
    }

    normalized, changed = gopay_pro_pool.normalize_slots_for_number_lines(
        slots,
        ["+628100000001----token-1", "+628100000003----token-3"],
        now=456,
    )

    assert changed == 1
    assert normalized["slot-01"]["id"] == "slot-01"
    assert normalized["slot-01"]["state"] == "WALLET_READY"
    assert normalized["slot-01"]["card"] == "+628100000001----token-1"
    assert normalized["slot-02"] == {
        "id": "slot-02",
        "card": "+628100000003----token-3",
        "full_phone": "+628100000003",
        "phone": "8100000003",
        "state": "EMPTY",
        "updated_at": 456,
    }


def test_normalize_slots_for_number_lines_fills_missing_ids_without_number_pool():
    normalized, changed = gopay_pro_pool.normalize_slots_for_number_lines(
        {
            "slot-01": {"state": "EMPTY"},
            "slot-02": {"id": "slot-02", "state": "WALLET_READY"},
            "metadata": "kept",
        },
        [],
        now=456,
    )

    assert changed == 1
    assert normalized["slot-01"]["id"] == "slot-01"
    assert normalized["slot-02"]["id"] == "slot-02"
    assert normalized["metadata"] == "kept"


def test_ready_slot_prefix_from_slots_returns_required_prefix_boundary():
    slots = {
        "slot-03": {"id": "slot-03", "state": "WALLET_READY"},
        "slot-01": {"id": "slot-01", "state": "WALLET_READY"},
        "slot-02": {"id": "slot-02", "state": "FAILED"},
        "slot-x": {"id": "slot-x", "state": "WALLET_READY"},
    }

    assert gopay_pro_pool.ready_slot_prefix_from_slots(slots, 1) == (2, 1)
    assert gopay_pro_pool.ready_slot_prefix_from_slots(slots, 2) == (2, 3)
    assert gopay_pro_pool.ready_slot_prefix_from_slots(slots, 3) == (2, 3)


def test_release_no_trial_slots_matches_round_tokens_or_explicit_slot_ids():
    slots = {
        "slot-01": {"id": "slot-01", "state": "NO_TRIAL", "access_token": "token-a"},
        "slot-02": {"id": "slot-02", "state": "NO_TRIAL", "accessToken": "token-b"},
        "slot-03": {"id": "slot-03", "state": "NO_TRIAL", "access_token": "token-c"},
        "slot-04": {"id": "slot-04", "state": "FAILED", "access_token": "token-a"},
    }

    next_slots, changed = gopay_pro_pool.release_no_trial_slots(
        slots,
        round_tokens={"Bearer token-a"},
        slot_ids={"slot-02"},
        now=789,
    )

    assert changed == 2
    assert next_slots["slot-01"]["state"] == "WALLET_READY"
    assert next_slots["slot-02"]["state"] == "WALLET_READY"
    assert next_slots["slot-03"]["state"] == "NO_TRIAL"
    assert next_slots["slot-04"]["state"] == "FAILED"
    assert next_slots["slot-01"]["updated_at"] == 789


def test_release_no_trial_slots_releases_all_when_round_tokens_is_none():
    next_slots, changed = gopay_pro_pool.release_no_trial_slots(
        {
            "slot-01": {"id": "slot-01", "state": "NO_TRIAL"},
            "slot-02": {"id": "slot-02", "state": "WALLET_READY"},
        },
        round_tokens=None,
        slot_ids=None,
        now=789,
    )

    assert changed == 1
    assert next_slots["slot-01"]["state"] == "WALLET_READY"
    assert next_slots["slot-02"]["state"] == "WALLET_READY"


def test_mark_midtrans_charge_202_slots_marks_requested_slots_only():
    next_slots, marked = gopay_pro_pool.mark_midtrans_charge_202_slots(
        {
            "slot-01": {"id": "slot-01", "state": "FAILED"},
            "legacy": {"id": "slot-02", "state": "FAILED"},
            "slot-03": {"id": "slot-03", "state": "FAILED"},
        },
        {"slot-02", "slot-03"},
        now=1234,
    )

    assert marked == ["slot-02", "slot-03"]
    assert "midtrans_charge_202" not in next_slots["slot-01"]
    assert next_slots["legacy"]["midtrans_charge_202"] is True
    assert next_slots["legacy"]["midtrans_charge_202_at"] == 1234
    assert next_slots["slot-03"]["updated_at"] == 1234


def test_slots_in_states_filters_and_sorts_by_slot_index():
    slots = {
        "slot-10": {"state": "FAILED"},
        "slot-02": {"state": "FAILED"},
        "slot-01": {"state": "WALLET_READY"},
    }

    assert gopay_pro_pool.slots_in_states(slots, ["slot-10", "slot-01", "slot-02"], {"FAILED"}) == [
        "slot-02",
        "slot-10",
    ]


def test_reset_unusable_ready_slots_requires_refreshable_tokens():
    next_slots, changed = gopay_pro_pool.reset_unusable_ready_slots(
        {
            "slot-01": {"state": "WALLET_READY", "access_token": "access", "refresh_token": "refresh"},
            "slot-02": {"state": "WALLET_READY", "access_token": "access"},
            "slot-03": {
                "state": "WALLET_READY",
                "access_token": "access",
                "refresh_token": "refresh",
                "error": "缺少 refresh_token",
            },
            "slot-04": {"state": "PLUS_PAYING"},
        },
        now=4567,
    )

    assert changed == 2
    assert next_slots["slot-01"]["state"] == "WALLET_READY"
    assert next_slots["slot-02"]["state"] == "FAILED"
    assert next_slots["slot-03"]["state"] == "FAILED"
    assert next_slots["slot-02"]["updated_at"] == 4567
    assert "缺少可刷新 GoPay token" in next_slots["slot-03"]["error"]
    assert next_slots["slot-04"]["state"] == "PLUS_PAYING"


def test_reset_stuck_paying_slots_releases_only_error_slots():
    next_slots, changed = gopay_pro_pool.reset_stuck_paying_slots(
        {
            "slot-01": {"state": "PLUS_PAYING", "error": "payment failed"},
            "slot-02": {"state": "PLUS_PAYING", "error": ""},
            "slot-03": {"state": "FAILED", "error": "payment failed"},
        },
        now=9876,
    )

    assert changed == 1
    assert next_slots["slot-01"]["state"] == "WALLET_READY"
    assert next_slots["slot-01"]["updated_at"] == 9876
    assert next_slots["slot-02"]["state"] == "PLUS_PAYING"
    assert next_slots["slot-03"]["state"] == "FAILED"


def test_build_status_payload_shapes_web_status_fields():
    tasks = [{"task_id": f"task-{index}", "command": "gopay-pro"} for index in range(10)]

    payload = gopay_pro_pool.build_status_payload(
        root="D:/CNgopay",
        exists=True,
        config={
            "pool": {
                "concurrency": 3,
                "gpt_mode": "plus",
                "number_pool_file": "numbers.txt",
                "provided_tokens_file": "tokens.txt",
            }
        },
        state={
            "slots": {
                "slot-02": {
                    "state": "FAILED",
                    "full_phone": "+628100000002",
                    "midtrans_charge_202": True,
                    "midtrans_charge_202_at": 123,
                },
                "slot-01": {"state": "WALLET_READY", "phone": "8100000001"},
                "metadata": "ignored",
            }
        },
        number_lines=["+6281----sms", "# disabled", ""],
        token_lines=["token-a", "# disabled"],
        waf_cooldown={"until": 111, "remaining_seconds": 22, "reason": "WAF"},
        tasks=tasks,
        commands={"harvest", "register"},
    )

    assert payload["root"] == "D:/CNgopay"
    assert payload["exists"] is True
    assert payload["config"] == {
        "slots": 1,
        "concurrency": 3,
        "gptMode": "plus",
        "numberPoolFile": "numbers.txt",
        "tokenFile": "tokens.txt",
    }
    assert payload["counts"] == {"numbers": 1, "tokens": 1}
    assert payload["cooldowns"] == {
        "registerWafUntil": 111,
        "registerWafRemainingSeconds": 22,
        "registerWafReason": "WAF",
    }
    assert payload["commands"] == ["harvest", "register"]
    assert [slot["id"] for slot in payload["slots"]] == ["slot-01", "slot-02"]
    assert payload["slots"][0]["displayPhone"] == "81000****001"
    assert payload["slots"][1]["displayPhone"] == "+6281****002"
    assert payload["slots"][1]["midtransCharge202"] is True
    assert payload["slots"][1]["midtransCharge202At"] == 123
    assert payload["stateCounts"] == {"WALLET_READY": 1, "FAILED": 1}
    assert len(payload["tasks"]) == 8


def test_build_status_payload_uses_defaults_for_missing_pool_config():
    payload = gopay_pro_pool.build_status_payload(
        root="root",
        exists=False,
        config={},
        state={"slots": {"slot-01": {}}},
        number_lines=[],
        token_lines=[],
        waf_cooldown={},
        tasks=[],
        commands=set(),
    )

    assert payload["config"] == {
        "slots": 0,
        "concurrency": 0,
        "gptMode": "",
        "numberPoolFile": "pool_numbers.txt",
        "tokenFile": "pool_tokens.txt",
    }
    assert payload["cooldowns"] == {
        "registerWafUntil": None,
        "registerWafRemainingSeconds": None,
        "registerWafReason": None,
    }
    assert payload["stateCounts"] == {"UNKNOWN": 1}
