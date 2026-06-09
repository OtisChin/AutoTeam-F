from autotoken.services import team_cleanup


def test_local_account_emails_excludes_main_and_normalizes():
    accounts = [
        {"email": "Owner@example.com"},
        {"email": " User@example.com "},
        {"email": ""},
    ]

    assert team_cleanup.local_account_emails(
        accounts,
        is_main_account_email=lambda email: email == "owner@example.com",
    ) == {"user@example.com"}


def test_split_local_and_external_members_preserves_order():
    members = [
        {"email": "local@example.com", "role": "member"},
        {"email": "external@example.com", "role": "member"},
        {"email": "LOCAL@example.com", "role": "admin"},
    ]

    local, external = team_cleanup.split_local_and_external_members(members, {"local@example.com"})

    assert local == [members[0], members[2]]
    assert external == [members[1]]


def test_removal_count_defaults_to_five_and_never_goes_negative():
    assert team_cleanup.removal_count(total_members=7, max_seats=None) == (2, 5)
    assert team_cleanup.removal_count(total_members=3, max_seats=5) == (0, 5)
    assert team_cleanup.removal_count(total_members=7, max_seats=4) == (3, 4)


def test_removable_members_prioritizes_exhausted_then_oldest_created_at():
    local_members = [
        {"email": "new@example.com"},
        {"email": "old@example.com"},
        {"email": "exhausted-new@example.com"},
        {"email": "exhausted-old@example.com"},
    ]
    accounts = [
        {"email": "new@example.com", "status": "active", "created_at": 20},
        {"email": "old@example.com", "status": "active", "created_at": 10},
        {"email": "exhausted-new@example.com", "status": "exhausted", "created_at": 40},
        {"email": "exhausted-old@example.com", "status": "exhausted", "created_at": 30},
    ]

    removable = team_cleanup.removable_members(local_members, accounts, exhausted_status="exhausted")

    assert [member["email"] for member in removable] == [
        "exhausted-old@example.com",
        "exhausted-new@example.com",
        "old@example.com",
        "new@example.com",
    ]


def test_pending_invites_for_local_accounts_requires_local_email_and_id():
    invites = [
        {"email_address": "local@example.com", "id": "invite-1"},
        {"email_address": "LOCAL@example.com", "id": ""},
        {"email_address": "external@example.com", "id": "invite-2"},
    ]

    assert team_cleanup.pending_invites_for_local_accounts(invites, {"local@example.com"}) == [invites[0]]
