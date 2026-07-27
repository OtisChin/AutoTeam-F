from autotoken.payments import plus_trial


class FakeCheckoutExtractor:
    calls = []

    def __init__(self, credentials, config, *, session_factory=None, sleeper=None, logger=None):
        self.credentials = credentials
        self.config = config
        self.session_factory = session_factory
        self.sleeper = sleeper
        self.logger = logger
        self.calls.append(self)

    def extract(self):
        return plus_trial.CheckoutResult(
            ok=True,
            long_url="https://chatgpt.com/checkout/openai_llc/oaics_trial",
            cs_id="oaics_trial",
            processor_entity="openai_llc",
            billing_country=self.config.billing_country,
            currency=self.config.currency,
            payment_locale=self.config.payment_locale,
            amount_verification="verified_zero",
            amount_minor=0,
            amount_currency=self.config.currency,
        )


def test_generate_plus_trial_checkout_link_maps_payload_and_environment_to_simon_extractor(monkeypatch):
    FakeCheckoutExtractor.calls = []
    monkeypatch.setattr(plus_trial, "CheckoutExtractor", FakeCheckoutExtractor)
    monkeypatch.setenv("PLUS_TRIAL_CHECKOUT_PROXY_COUNTRY", "us")
    monkeypatch.setenv("PLUS_TRIAL_UPDATE_PROXY_COUNTRY", "tr")
    monkeypatch.setenv("PLUS_TRIAL_SKIP_PROXY_CHECK", "1")
    monkeypatch.setenv("PLUS_TRIAL_PROMO_CAMPAIGN_ID", "trial-campaign")

    result = plus_trial.generate_plus_trial_checkout_link(
        "token-1",
        {
            "plan_name": "chatgptplusplan",
            "checkout_ui_mode": "hosted",
            "billing_details": {"country": "PH", "currency": "PHP"},
            "session_cookie": "oai-did=device-1; __Secure-next-auth.session-token=session-1",
        },
        sleeper=lambda _seconds: None,
        logger=lambda _message: None,
    )

    extractor = FakeCheckoutExtractor.calls[0]
    assert extractor.credentials.access_token == "token-1"
    assert extractor.credentials.session_cookie == "oai-did=device-1; __Secure-next-auth.session-token=session-1"
    assert extractor.config.billing_country == "PH"
    assert extractor.config.currency == "PHP"
    assert extractor.config.checkout_proxy_country == "US"
    assert extractor.config.update_proxy_country == "TR"
    assert extractor.config.promo_campaign_id == "trial-campaign"
    assert extractor.config.verify_proxy_country is False
    assert result == {
        "url": "https://chatgpt.com/checkout/openai_llc/oaics_trial",
        "checkout_session_id": "oaics_trial",
        "processor_entity": "openai_llc",
        "chatgpt_checkout_url": "https://chatgpt.com/checkout/openai_llc/oaics_trial",
        "long_url": "https://chatgpt.com/checkout/openai_llc/oaics_trial",
        "billing_country": "PH",
        "currency": "PHP",
        "payment_locale": "en",
        "amount_verification": "verified_zero",
        "amount_minor": 0,
        "amount_currency": "PHP",
        "checkout_flow": "plus_trial",
    }


def test_generate_plus_trial_checkout_link_ignores_playwright_proxy(monkeypatch):
    FakeCheckoutExtractor.calls = []
    monkeypatch.setattr(plus_trial, "CheckoutExtractor", FakeCheckoutExtractor)
    monkeypatch.delenv("PLUS_TRIAL_CHECKOUT_PROXY", raising=False)
    monkeypatch.delenv("PLUS_TRIAL_UPDATE_PROXY", raising=False)
    monkeypatch.delenv("CLIPROXY_HOST", raising=False)
    monkeypatch.delenv("CLIPROXY_USERNAME", raising=False)
    monkeypatch.delenv("CLIPROXY_PASSWORD", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_PROXY_URL", "http://proxy.example:8080")

    plus_trial.generate_plus_trial_checkout_link(
        "token-1",
        {"billing_details": {"country": "PH", "currency": "PHP"}},
        sleeper=lambda _seconds: None,
        logger=lambda _message: None,
    )

    config = FakeCheckoutExtractor.calls[0].config
    assert config.checkout_proxy == ""
    assert config.update_proxy == ""
    assert config.verify_proxy_country is False


def test_checkout_extractor_allows_direct_connection_when_no_proxy_configured(monkeypatch):
    monkeypatch.delenv("CLIPROXY_HOST", raising=False)
    monkeypatch.delenv("CLIPROXY_USERNAME", raising=False)
    monkeypatch.delenv("CLIPROXY_PASSWORD", raising=False)

    extractor = plus_trial.CheckoutExtractor(
        plus_trial.Credentials(access_token="token-1"),
        plus_trial.ExtractorConfig(
            cliproxy_host="",
            cliproxy_username="",
            cliproxy_password="",
            checkout_proxy="",
            update_proxy="",
            verify_proxy_country=False,
        ),
        session_factory=lambda: object(),
    )

    assert extractor._stage_proxies() == ("", "")


def test_generate_plus_trial_checkout_link_disables_country_check_for_direct_mode(monkeypatch):
    FakeCheckoutExtractor.calls = []
    monkeypatch.setattr(plus_trial, "CheckoutExtractor", FakeCheckoutExtractor)
    monkeypatch.delenv("PLUS_TRIAL_CHECKOUT_PROXY", raising=False)
    monkeypatch.delenv("PLUS_TRIAL_UPDATE_PROXY", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_PROXY_URL", raising=False)
    monkeypatch.delenv("CLIPROXY_USERNAME", raising=False)
    monkeypatch.delenv("CLIPROXY_PASSWORD", raising=False)

    plus_trial.generate_plus_trial_checkout_link(
        "token-1",
        {"billing_details": {"country": "PH", "currency": "PHP"}},
        sleeper=lambda _seconds: None,
        logger=lambda _message: None,
    )

    config = FakeCheckoutExtractor.calls[0].config
    assert config.checkout_proxy == ""
    assert config.update_proxy == ""
    assert config.verify_proxy_country is False


def test_generate_plus_trial_checkout_link_uses_payload_protocol_proxies(monkeypatch):
    FakeCheckoutExtractor.calls = []
    monkeypatch.setattr(plus_trial, "CheckoutExtractor", FakeCheckoutExtractor)
    monkeypatch.setenv("PLUS_TRIAL_CHECKOUT_PROXY", "socks5h://env-checkout.example:1080")
    monkeypatch.setenv("PLUS_TRIAL_UPDATE_PROXY", "socks5h://env-update.example:1080")

    plus_trial.generate_plus_trial_checkout_link(
        "token-1",
        {
            "billing_details": {"country": "PH", "currency": "PHP"},
            "checkout_proxy": "socks5h://payload-checkout.example:1080",
            "update_proxy": "socks5h://payload-update.example:1080",
            "checkout_proxy_country": "PH",
            "update_proxy_country": "PH",
            "verify_proxy_country": True,
        },
        sleeper=lambda _seconds: None,
        logger=lambda _message: None,
    )

    config = FakeCheckoutExtractor.calls[0].config
    assert config.checkout_proxy == "socks5h://payload-checkout.example:1080"
    assert config.update_proxy == "socks5h://payload-update.example:1080"
    assert config.checkout_proxy_country == "PH"
    assert config.update_proxy_country == "PH"
    assert config.verify_proxy_country is True
