import pytest

from autotoken.services.mailcom_password import change_mailcom_password


class FakeResponse:
    def __init__(self, text="", status_code=200, url="", headers=None):
        self.text = text
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


def login_page():
    return """
    <form id="loginForm" method="post" action="https://login.mail.com/login">
      <input type="hidden" name="service" value="ciss"/>
      <input type="hidden" name="successURL" value="https://account.mail.com/ciss/myAccountOverview?serviceid=ciss"/>
      <input type="hidden" name="statistics" value="stat"/>
      <input type="text" name="username"/>
      <input type="password" name="password"/>
      <input type="submit" name="login" value="Log in"/>
    </form>
    """


def overview_page():
    return """
    <html>
      <a href="./myAccountOverview?0-1.-frequentLinksPanel-frequentLinks-changePasswordLink&amp;srttkn=token">
        Change password
      </a>
    </html>
    """


def password_page():
    return """
    <form id="id3" method="post" action="./passwordChange?1-1.-form&amp;srttkn=token">
      <input type="hidden" name="editPanel:username" value="one@mail.com"/>
      <input type="password" name="editPanel:currentPasswordPanel:topWrapper:inputWrapper:input"/>
      <input type="password" name="editPanel:newPasswordFieldPanel:topWrapper:inputWrapper:input"/>
      <input type="password" name="editPanel:retypeNewPasswordFieldPanel:topWrapper:inputWrapper:input"/>
      <button id="id4">Save changes</button>
    </form>
    """


def test_change_mailcom_password_posts_ciss_password_form():
    session = FakeSession(
        [
            FakeResponse(login_page(), url="https://account.mail.com/ciss/login"),
            FakeResponse("", status_code=303, headers={"location": "https://account.mail.com/ciss/myAccountOverview?serviceid=ciss&ott=1"}),
            FakeResponse(overview_page(), url="https://account.mail.com/ciss/myAccountOverview?serviceid=ciss"),
            FakeResponse(password_page(), url="https://account.mail.com/ciss/security/edit/passwordChange?1&srttkn=token"),
            FakeResponse('<section class="hint hint-success">Password changed</section>', url="https://account.mail.com/ciss/security"),
        ]
    )

    result = change_mailcom_password(
        "one@mail.com",
        "old-pass",
        "new-pass-123456",
        session_factory=lambda: session,
    )

    assert result["status"] == "success"
    login_post = session.calls[1]
    assert login_post[0] == "POST"
    assert login_post[1] == "https://login.mail.com/login"
    assert login_post[2]["data"]["username"] == "one@mail.com"
    assert login_post[2]["data"]["password"] == "old-pass"

    change_post = session.calls[4]
    assert change_post[0] == "POST"
    assert change_post[1] == "https://account.mail.com/ciss/security/edit/passwordChange?1-1.-form&srttkn=token&saveChanges=x"
    payload = change_post[2]["data"]
    assert payload["editPanel:currentPasswordPanel:topWrapper:inputWrapper:input"] == "old-pass"
    assert payload["editPanel:newPasswordFieldPanel:topWrapper:inputWrapper:input"] == "new-pass-123456"
    assert payload["editPanel:retypeNewPasswordFieldPanel:topWrapper:inputWrapper:input"] == "new-pass-123456"


def test_change_mailcom_password_raises_on_form_error():
    session = FakeSession(
        [
            FakeResponse(login_page(), url="https://account.mail.com/ciss/login"),
            FakeResponse("", status_code=303, headers={"location": "https://account.mail.com/ciss/myAccountOverview?serviceid=ciss&ott=1"}),
            FakeResponse(overview_page(), url="https://account.mail.com/ciss/myAccountOverview?serviceid=ciss"),
            FakeResponse(password_page(), url="https://account.mail.com/ciss/security/edit/passwordChange?1&srttkn=token"),
            FakeResponse(
                '<section class="hint hint-error"><span class="hint-headline">One or more entries could not be processed</span></section>',
                url="https://account.mail.com/ciss/security/edit/passwordChange?2&srttkn=token",
            ),
        ]
    )

    with pytest.raises(RuntimeError, match="One or more entries could not be processed"):
        change_mailcom_password("one@mail.com", "bad-old", "new-pass-123456", session_factory=lambda: session)
