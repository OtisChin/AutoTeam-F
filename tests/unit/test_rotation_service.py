from autotoken.services import rotation


def test_auto_reuse_skip_reason_detects_google_provider_and_domains():
    assert rotation.account_login_provider({"email": "user@example.com", "login_provider": "google"}) == "google"
    assert rotation.account_login_provider({"email": "user@example.com", "auth_provider": "google"}) == "google"
    assert rotation.account_login_provider({"email": "bubblehuntr@gmail.com"}) == "google"
    assert rotation.account_login_provider({"email": "old@googlemail.com"}) == "google"
    assert rotation.auto_reuse_skip_reason({"email": "bubblehuntr@gmail.com"}) == rotation.GOOGLE_AUTO_REUSE_SKIP_REASON
    assert rotation.auto_reuse_skip_reason({"email": "user@example.com"}) is None


def test_standby_reuse_candidates_filters_main_recovered_and_excluded_accounts():
    accounts = [
        {"email": "main@example.com", "_quota_recovered": True},
        {"email": "old-1@example.com", "_quota_recovered": False},
        {"email": "old-2@example.com", "_quota_recovered": True},
        {"email": "old-3@example.com", "_quota_recovered": True},
        {"email": ""},
    ]

    candidates = rotation.standby_reuse_candidates(
        accounts,
        is_main_account_email=lambda email: email == "main@example.com",
        recovered_only=True,
        exclude_email="OLD-3@example.com",
    )

    assert candidates == [{"email": "old-2@example.com", "_quota_recovered": True}]


def test_standby_reuse_candidates_can_keep_unrecovered_accounts_for_quota_probe():
    accounts = [
        {"email": "old-1@example.com", "_quota_recovered": False},
        {"email": "old-2@example.com", "_quota_recovered": True},
    ]

    assert rotation.standby_reuse_candidates(
        accounts,
        is_main_account_email=lambda _email: False,
    ) == accounts


def test_estimate_current_member_count_uses_local_active_when_api_count_is_invalid():
    assert rotation.estimate_current_member_count(
        api_count=0,
        initial_api_count=9,
        removed_now=2,
        local_active_count=4,
    ) == (4, True, False)


def test_estimate_current_member_count_uses_conservative_removed_count():
    assert rotation.estimate_current_member_count(
        api_count=8,
        initial_api_count=10,
        removed_now=4,
        local_active_count=5,
    ) == (6, False, True)


def test_vacancy_count_keeps_negative_overfill_signal():
    assert rotation.vacancy_count(target=5, current_count=7) == -2


def test_overfill_cleanup_candidates_excludes_main_and_sorts_low_remaining_quota_first():
    accounts = [
        {"email": "main@example.com", "status": "active", "last_quota": {"primary_pct": 100}},
        {"email": "high@example.com", "status": "active", "last_quota": {"primary_pct": 10}},
        {"email": "low@example.com", "status": "active", "last_quota": {"primary_pct": 95}},
        {"email": "standby@example.com", "status": "standby", "last_quota": {"primary_pct": 100}},
        {"email": "malformed@example.com", "status": "active", "last_quota": {"primary_pct": "not-a-number"}},
    ]

    candidates = rotation.overfill_cleanup_candidates(
        accounts,
        is_main_account_email=lambda email: email == "main@example.com",
        active_status="active",
    )

    assert [candidate["email"] for candidate in candidates] == [
        "low@example.com",
        "high@example.com",
        "malformed@example.com",
    ]
