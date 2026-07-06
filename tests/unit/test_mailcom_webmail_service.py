from autotoken.services.mailcom_webmail import fetch_mailcom_messages


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


def home_page():
    return """
    <form action="https://login.mail.com/login" method="post" data-mod-name="loginform">
      <input type="hidden" name="service" value="mailint"/>
      <input type="hidden" name="successURL" value="https://$(clientName)-$(dataCenter).mail.com/login"/>
      <input type="hidden" name="edition" value="us"/>
      <input type="text" name="username"/>
      <input type="password" name="password"/>
    </form>
    """


def navigator_page():
    return """
    <script>
      location.replace('https://lightmailer.mail.com/start?device=desktop&ott=one-time-token&hint=unsupported');
    </script>
    """


def folderlist_page():
    return """
    <ul class="sidebar__folder-list">
      <li>
        <a class="list-group-item" href="./messagelist?folderId=1782453692293812158" data-webdriver="INBOX:Inbox">
          Inbox
        </a>
      </li>
    </ul>
    """


def messagelist_page():
    return """
    <ul id="mail-list">
      <li class="message-list__item mail-panel">
        <dd class="mail-header__subject">Your temporary OpenAI verification code</dd>
        <dd class="mail-header__sender" title="&quot;OpenAI&quot; &lt;noreply@tm.openai.com&gt;">OpenAI</dd>
        <dd class="mail-header__date" title="Saturday, July 04, 2026 at 7:51 AM">7/4/26</dd>
        <ul class="mail-header__details">
          <li class="mail-header__detail-element iconset icon-status-read is-invisible">Read</li>
        </ul>
        <a class="message-list__link mail-panel__link"
           href="./messagedetail?folderId=1782453692293812158&amp;mailIndex=1&amp;mailId=1783144315681730472">
          Open E-mail
        </a>
      </li>
    </ul>
    """


def detail_page():
    return """
    <div class="message-detail-panel__body">
      <iframe id="bodyIFrame" src="./mailbody/1783144315681730472/false"></iframe>
    </div>
    """


def body_page():
    return """
    <html>
      <body>
        <p>Your temporary OpenAI verification code is 123456.</p>
      </body>
    </html>
    """


def test_fetch_mailcom_messages_logs_into_official_lightmailer_and_reads_body():
    session = FakeSession(
        [
            FakeResponse(home_page(), url="https://www.mail.com/"),
            FakeResponse("", status_code=303, headers={"location": "https://navigator-lxa.mail.com/login?ott=one-time-token"}),
            FakeResponse(navigator_page(), url="https://navigator-lxa.mail.com/login?ott=one-time-token"),
            FakeResponse("", url="https://lightmailer.mail.com/start?0&device=desktop"),
            FakeResponse(folderlist_page(), url="https://lightmailer.mail.com/folderlist?1"),
            FakeResponse(messagelist_page(), url="https://lightmailer.mail.com/messagelist?2&folderId=1782453692293812158"),
            FakeResponse(detail_page(), url="https://lightmailer.mail.com/messagedetail?3&folderId=1782453692293812158"),
            FakeResponse(body_page(), url="https://lightmailer.mail.com/mailbody/1783144315681730472/false"),
        ]
    )

    messages = fetch_mailcom_messages(
        {"email": "one@mail.com", "mail_password": "mail-pass"},
        size=5,
        session_factory=lambda: session,
    )

    assert [call[1] for call in session.calls] == [
        "https://www.mail.com/",
        "https://login.mail.com/login",
        "https://navigator-lxa.mail.com/login?ott=one-time-token",
        "https://lightmailer.mail.com/start?device=desktop&ott=one-time-token&hint=unsupported",
        "https://lightmailer.mail.com/folderlist?tep=startup&fcs=true",
        "https://lightmailer.mail.com/messagelist?folderId=1782453692293812158",
        "https://lightmailer.mail.com/messagedetail?folderId=1782453692293812158&mailIndex=1&mailId=1783144315681730472",
        "https://lightmailer.mail.com/mailbody/1783144315681730472/false",
    ]
    assert all("ms.lqqq.cc" not in call[1] for call in session.calls)
    assert messages[0]["id"] == "1783144315681730472"
    assert messages[0]["subject"] == "Your temporary OpenAI verification code"
    assert messages[0]["sendEmail"] == '"OpenAI" <noreply@tm.openai.com>'
    assert messages[0]["text"] == "Your temporary OpenAI verification code is 123456."
    assert messages[0]["raw"]["source"] == "mail.com-lightmailer"


def test_fetch_mailcom_messages_returns_empty_when_inbox_has_no_messages():
    session = FakeSession(
        [
            FakeResponse(home_page(), url="https://www.mail.com/"),
            FakeResponse("", status_code=303, headers={"location": "https://navigator-lxa.mail.com/login?ott=one-time-token"}),
            FakeResponse(navigator_page(), url="https://navigator-lxa.mail.com/login?ott=one-time-token"),
            FakeResponse("", url="https://lightmailer.mail.com/start?0&device=desktop"),
            FakeResponse(folderlist_page(), url="https://lightmailer.mail.com/folderlist?1"),
            FakeResponse("<ul id='mail-list'></ul>", url="https://lightmailer.mail.com/messagelist?2&folderId=1782453692293812158"),
        ]
    )

    assert fetch_mailcom_messages({"email": "one@mail.com", "mail_password": "mail-pass"}, session_factory=lambda: session) == []
