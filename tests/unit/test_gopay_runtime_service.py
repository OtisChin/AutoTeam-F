from autotoken import api
from autotoken.services import gopay_runtime


def test_runtime_seconds_are_clamped_and_rounded():
    assert gopay_runtime.normalize_runtime_seconds("3.14159", 1, minimum=0, maximum=10) == 3.142
    assert gopay_runtime.normalize_runtime_seconds("-5", 1, minimum=0, maximum=10) == 0.0
    assert gopay_runtime.normalize_runtime_seconds("50", 1, minimum=0, maximum=10) == 10.0
    assert gopay_runtime.normalize_runtime_seconds("bad", 2.5, minimum=0, maximum=10) == 2.5


def test_runtime_concurrency_is_clamped_and_uses_default_on_bad_input():
    assert gopay_runtime.normalize_runtime_concurrency("3", 1) == 3
    assert gopay_runtime.normalize_runtime_concurrency("0", 1) == 1
    assert gopay_runtime.normalize_runtime_concurrency("50", 1) == 10
    assert gopay_runtime.normalize_runtime_concurrency(None, 7) == 7
    assert gopay_runtime.normalize_runtime_concurrency("bad", 12) == 10
    assert gopay_runtime.normalize_runtime_concurrency("bad", 0) == 1


def test_balance_poll_interval_env_parsing_prefers_explicit_positive_list(monkeypatch):
    monkeypatch.setenv("GOPAY_WALLET_BALANCE_POLL_INTERVALS", " 1, bad; 2 | -3 0 4 ")
    monkeypatch.setenv("GOPAY_WALLET_BALANCE_POLL_INTERVAL_SECONDS", "99")
    monkeypatch.setenv("GOPAY_WALLET_BALANCE_POLL_ATTEMPTS", "9")

    assert gopay_runtime.wallet_balance_poll_intervals_from_env() == [1.0, 2.0, 4.0]
    assert gopay_runtime.default_wallet_balance_poll_interval_seconds() == 1.0
    assert gopay_runtime.default_wallet_balance_wait_seconds() == 7.0


def test_balance_poll_interval_env_falls_back_to_bounded_attempts(monkeypatch):
    monkeypatch.delenv("GOPAY_WALLET_BALANCE_POLL_INTERVALS", raising=False)
    monkeypatch.setenv("GOPAY_WALLET_BALANCE_POLL_INTERVAL_SECONDS", "0.1")
    monkeypatch.setenv("GOPAY_WALLET_BALANCE_POLL_ATTEMPTS", "99")

    assert gopay_runtime.wallet_balance_poll_intervals_from_env() == [1.0] * 30


def test_build_balance_poll_intervals_preserves_final_partial_interval():
    assert gopay_runtime.build_balance_poll_intervals(25, 10) == [10.0, 10.0, 5.0]
    assert gopay_runtime.build_balance_poll_intervals(0, 10) == [0.0]
    assert gopay_runtime.build_balance_poll_intervals(10, 0) == [0.0]


def test_gopay_runtime_env_defaults_and_bounds(monkeypatch):
    monkeypatch.setenv("GOPAY_AUTO_REGISTER_BIND_DELAY_MIN", "20")
    monkeypatch.setenv("GOPAY_AUTO_REGISTER_BIND_DELAY_MAX", "10")
    monkeypatch.setattr(gopay_runtime.random, "uniform", lambda low, high: low + high)
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_NO_TRANSFER_BIND_WAIT_SECONDS", "-5")
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_NO_TRANSFER_RETRY_WAITS", "60, bad, 0, 120")
    monkeypatch.setenv("GOPAY_AUTO_SIGNUP_PREFETCH_WALLETS", "9")

    assert gopay_runtime.auto_register_bind_delay_seconds() == 30.0
    assert gopay_runtime.auto_signup_no_transfer_bind_wait_seconds() == 0.0
    assert gopay_runtime.auto_signup_no_transfer_retry_waits_seconds() == [60.0, 120.0]
    assert gopay_runtime.auto_signup_prefetch_wallets() == 2


def test_local_signup_url_rewrite_only_retargets_loopback_hosts():
    assert gopay_runtime.rewrite_local_signup_url_for_base(
        "http://127.0.0.1:8787/otp/gopay-signup/token?x=1#frag",
        "https://public.example.com/base",
    ) == "https://public.example.com/otp/gopay-signup/token?x=1#frag"
    assert gopay_runtime.rewrite_local_signup_url_for_base(
        "https://sms.example.com/otp/gopay-signup/token",
        "https://public.example.com",
    ) == "https://sms.example.com/otp/gopay-signup/token"
    assert gopay_runtime.rewrite_local_signup_url_for_base(
        "http://127.0.0.1:8787/other/token",
        "https://public.example.com",
    ) == "http://127.0.0.1:8787/other/token"


def test_phone_account_sms_url_rewrite_preserves_other_fields():
    account = {"phone_number": "+6281", "smsUrl": "http://localhost:8787/otp/gopay-signup/demo"}

    assert gopay_runtime.rewrite_phone_account_sms_url_for_base(account, "https://public.example.com") == {
        "phone_number": "+6281",
        "smsUrl": "http://localhost:8787/otp/gopay-signup/demo",
        "sms_url": "https://public.example.com/otp/gopay-signup/demo",
    }


def test_phone_masking_and_pool_country_normalization_are_stable():
    assert gopay_runtime.mask_phone_for_log("+62 812-3456-7890") == "***7890(len=13)"
    assert gopay_runtime.mask_phone_for_log("1234") == "***"
    assert gopay_runtime.mask_phone_for_log("") == ""
    assert gopay_runtime.normalized_pool_country("+62") == "62"
    assert gopay_runtime.normalized_pool_country("") == "62"


def test_api_keeps_compatibility_wrappers_for_gopay_runtime_helpers():
    assert api._normalize_gopay_runtime_seconds("12.3456", 1) == 12.346
    assert api._normalize_gopay_runtime_concurrency("12", 1) == 10
    assert api._build_gopay_balance_poll_intervals(5, 2) == [2.0, 2.0, 1.0]
    assert api._rewrite_local_gopay_signup_url_for_base(
        "http://localhost:8787/otp/gopay-signup/demo",
        "https://public.example.com",
    ) == "https://public.example.com/otp/gopay-signup/demo"
