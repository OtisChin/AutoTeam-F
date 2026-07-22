import pytest

from autotoken.auth import invite


def test_register_with_invite_is_disabled():
    with pytest.raises(RuntimeError) as exc_info:
        invite.register_with_invite(None, "https://example.com/invite", "user@example.com", None)

    assert "Team invite 注册链路已禁用" in str(exc_info.value)


def test_invite_run_is_disabled():
    with pytest.raises(RuntimeError) as exc_info:
        invite.run()

    assert "Team invite 注册链路已禁用" in str(exc_info.value)
