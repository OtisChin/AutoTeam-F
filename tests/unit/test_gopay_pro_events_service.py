from autotoken.services import gopay_pro_events


def test_text_classifiers_detect_gopay_pro_script_failures():
    assert gopay_pro_events.text_has_waf_block("403 WAF Block Page")
    assert gopay_pro_events.text_has_waf_block("domain-config-1256704386.cos.accelerate.myqcloud")
    assert gopay_pro_events.text_has_register_ratelimit("注册/登录失败: [ratelimited] 限流")
    assert gopay_pro_events.text_has_register_ratelimit("rate limit exceeded")
    assert gopay_pro_events.text_has_token_invalidated("Authentication token has been invalidated")
    assert gopay_pro_events.text_has_chatgpt_checkout_unauthorized("chatgpt checkout 401")


def test_register_ratelimited_slots_from_log_deduplicates_slots():
    log = "\n".join(
        [
            "[12:00:00] [slot-01] 注册/登录失败: [ratelimited] 限流",
            "[12:00:01] [slot-01] rate limit exceeded",
            "[12:00:02] [slot-02] rate limit exceeded",
            "[12:00:03] [slot-03] unrelated failure",
        ]
    )

    assert gopay_pro_events.register_ratelimited_slots_from_log(log) == ["slot-01", "slot-02"]


def test_harvest_started_and_terminal_events_keep_first_terminal_event_per_slot():
    log = "\n".join(
        [
            "[12:00:00] [slot-01] 开 Plus",
            "[12:00:01] [slot-02] 开Plus",
            "[12:00:02] [slot-01] ✅ Plus 开通成功",
            "[12:00:03] [slot-01] 无免费试用资格",
            "[12:00:04] [slot-02] 账号无免费试用资格",
            "[12:00:05] [slot-03] token_invalidated",
            "[12:00:06] [slot-04] chatgpt checkout 401",
        ]
    )

    assert gopay_pro_events.harvest_started_slots(log) == ["slot-01", "slot-02"]
    assert gopay_pro_events.harvest_terminal_events(log) == [
        {"kind": "success", "slot_id": "slot-01"},
        {"kind": "no_trial", "slot_id": "slot-02"},
        {"kind": "token_invalidated", "slot_id": "slot-03"},
        {"kind": "checkout_unauthorized", "slot_id": "slot-04"},
    ]


def test_slot_log_predicates_match_only_requested_slot():
    log = "\n".join(
        [
            "[12:00:00] [slot-01] token_invalidated",
            "[12:00:01] [slot-02] ❌ Plus 支付失败: chatgpt checkout 401: {",
            '"error": {"message": "Could not parse your authentication token."}',
            "[12:00:02] [slot-03] ✅ Plus 开通成功",
        ]
    )

    assert gopay_pro_events.slot_log_has_token_invalidated(log, "slot-01")
    assert not gopay_pro_events.slot_log_has_token_invalidated(log, "slot-02")
    assert gopay_pro_events.slot_log_has_chatgpt_checkout_unauthorized(log, "slot-02")
    assert not gopay_pro_events.slot_log_has_chatgpt_checkout_unauthorized(log, "slot-03")
    assert gopay_pro_events.slot_log_has_success(log, "slot-03")
    assert not gopay_pro_events.slot_log_has_success(log, "slot-01")


def test_harvest_failure_slot_extractors_deduplicate_results():
    log = "\n".join(
        [
            "[15:59:07] [slot-01] ❌ Plus 支付失败: midtrans charge denied: status=deny code=202",
            "[15:59:08] [slot-01] ❌ Plus 支付失败: midtrans charge denied: status=deny code=202",
            "[15:59:09] [slot-02] ❌ Plus 支付失败: payment/validate 重试后仍失败",
            "[15:59:10] [slot-02] ❌ Plus 支付失败: payment/validate 重试后仍失败",
            "[15:59:11] [slot-03] ❌ Plus 支付失败: chatgpt checkout 401",
        ]
    )

    assert gopay_pro_events.midtrans_charge_202_slots(log) == ["slot-01"]
    assert gopay_pro_events.payment_validate_failed_slots(log) == ["slot-02"]
    assert gopay_pro_events.harvest_checkout_unauthorized_slots(log) == ["slot-03"]
