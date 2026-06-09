import json

from autotoken import manager


class _FakeChatGPT:
    def __init__(self, members, invites):
        self.browser = True
        self.members = members
        self.invites = invites
        self.deleted_paths = []
        self.stopped = 0

    def start(self):
        self.browser = True

    def stop(self):
        self.browser = False
        self.stopped += 1

    def _api_fetch(self, method, path):
        if method == "GET" and path.endswith("/users"):
            return {"status": 200, "body": json.dumps({"items": self.members})}
        if method == "GET" and path.endswith("/invites"):
            return {"status": 200, "body": json.dumps({"invites": self.invites})}
        if method == "DELETE":
            self.deleted_paths.append(path)
            return {"status": 204, "body": ""}
        return {"status": 404, "body": ""}


def test_cmd_cleanup_removes_prioritized_local_members_and_local_invites(monkeypatch):
    members = [
        {"email": "external@example.com", "id": "user-external"},
        {"email": "new@example.com", "id": "user-new"},
        {"email": "old@example.com", "id": "user-old"},
        {"email": "exhausted@example.com", "id": "user-exhausted"},
    ]
    invites = [
        {"email_address": "new@example.com", "id": "invite-local"},
        {"email_address": "external@example.com", "id": "invite-external"},
    ]
    fake = _FakeChatGPT(members, invites)
    accounts = [
        {"email": "new@example.com", "status": "active", "created_at": 20},
        {"email": "old@example.com", "status": "active", "created_at": 10},
        {"email": "exhausted@example.com", "status": "exhausted", "created_at": 30},
    ]
    updates = []

    monkeypatch.setattr(manager, "get_chatgpt_account_id", lambda: "acct-1")
    monkeypatch.setattr(manager, "load_accounts", lambda: accounts)
    monkeypatch.setattr(manager, "_is_main_account_email", lambda _email: False)
    monkeypatch.setattr(manager, "ChatGPTTeamAPI", lambda: fake)
    monkeypatch.setattr(manager, "update_account", lambda email, **fields: updates.append((email, fields)))
    monkeypatch.setattr(manager, "_log_auto_cpa_sync_disabled", lambda _context: None)

    manager.cmd_cleanup(max_seats=2)

    assert fake.deleted_paths == [
        "/backend-api/accounts/acct-1/users/user-exhausted",
        "/backend-api/accounts/acct-1/users/user-old",
        "/backend-api/accounts/acct-1/invites/invite-local",
    ]
    assert updates == [
        ("exhausted@example.com", {"status": "standby"}),
        ("old@example.com", {"status": "standby"}),
    ]
    assert fake.stopped == 1
