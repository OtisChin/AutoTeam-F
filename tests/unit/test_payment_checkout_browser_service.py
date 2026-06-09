from autotoken.services import payment_checkout_browser


class FakeKeyboard:
    def __init__(self):
        self.pressed = []

    def press(self, key):
        self.pressed.append(key)


class FakePage:
    def __init__(self, *, url="", frames=None, body="", evaluate_result=None):
        self.url = url
        self.frames = frames or []
        self.main_frame = self.frames[0] if self.frames else None
        self.keyboard = FakeKeyboard()
        self.body = body
        self.evaluate_result = evaluate_result
        self.evaluated = []
        self.loaded = []
        self.waited = []

    def evaluate(self, script, *args):
        self.evaluated.append((script, args))
        if isinstance(self.evaluate_result, Exception):
            raise self.evaluate_result
        return self.evaluate_result

    def wait_for_load_state(self, state, timeout=None):
        self.loaded.append((state, timeout))

    def wait_for_timeout(self, timeout):
        self.waited.append(timeout)

    def locator(self, selector):
        return FakeBodyLocator(self.body)


class FakeBodyLocator:
    def __init__(self, body):
        self.body = body

    def inner_text(self, timeout=None):
        return self.body


class FakeFrame:
    def __init__(self, body="", *, raises=False):
        self.body = body
        self.raises = raises

    def locator(self, selector):
        assert selector == "body"
        if self.raises:
            raise RuntimeError("frame closed")
        return FakeBodyLocator(self.body)


class FakeApi:
    def __init__(self, page):
        self.page = page
        self.context = FakeContext()


class FakeContext:
    def __init__(self):
        self.pages = []

    def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page


def test_iter_page_frames_deduplicates_main_frame():
    frame = object()
    api = FakeApi(FakePage(frames=[frame, frame]))

    assert payment_checkout_browser.iter_page_frames(api) == [frame]


def test_suppress_address_autocomplete_ui_injects_style_script():
    page = FakePage()
    api = FakeApi(page)

    payment_checkout_browser.suppress_address_autocomplete_ui(api)

    assert page.evaluated
    assert "autotoken-hide-address-autocomplete" in page.evaluated[0][0]


def test_body_excerpt_with_frames_collects_unique_main_and_frame_text():
    main_frame = FakeFrame("Main should be skipped")
    duplicate_frame = FakeFrame("Main body")
    frame = FakeFrame("Frame body")
    failing_frame = FakeFrame(raises=True)
    page = FakePage(frames=[main_frame, duplicate_frame, frame, failing_frame], body=" Main body ")
    api = FakeApi(page)

    excerpt = payment_checkout_browser.body_excerpt_with_frames(api, limit=100)

    assert excerpt == "Main body\nFrame body"


def test_body_excerpt_with_frames_uses_limit_after_joining_chunks():
    page = FakePage(frames=[FakeFrame("Main frame"), FakeFrame("Frame body")], body="Main body")
    api = FakeApi(page)

    assert payment_checkout_browser.body_excerpt_with_frames(api, limit=12) == "Main body\nFr"


def test_sync_relevant_payment_page_prefers_primary_page_when_requested():
    pages = [
        FakePage(url="https://checkout.example/cs_1"),
        FakePage(url="https://primary.example/pay"),
        FakePage(url="https://checkout.example/cs_2"),
    ]
    api = FakeApi(FakePage(url="about:blank"))
    api.context.pages = pages

    selected = payment_checkout_browser.sync_relevant_payment_page(
        api,
        prefer_primary=True,
        is_primary_url=lambda url: "primary.example" in url,
        is_relevant_url=lambda url: "checkout.example" in url,
    )

    assert selected is pages[1]
    assert api.page is pages[1]


def test_sync_relevant_payment_page_uses_latest_relevant_then_latest_fallback():
    pages = [
        FakePage(url="https://unrelated.example/one"),
        FakePage(url="https://checkout.example/cs_1"),
        FakePage(url="https://unrelated.example/two"),
    ]
    api = FakeApi(FakePage(url="about:blank"))
    api.context.pages = pages

    selected = payment_checkout_browser.sync_relevant_payment_page(
        api,
        is_primary_url=lambda url: "primary.example" in url,
        is_relevant_url=lambda url: "checkout.example" in url,
    )

    assert selected is pages[1]
    assert api.page is pages[1]

    selected = payment_checkout_browser.sync_relevant_payment_page(
        api,
        is_primary_url=lambda url: "missing-primary.example" in url,
        is_relevant_url=lambda url: "missing-checkout.example" in url,
    )

    assert selected is pages[-1]
    assert api.page is pages[-1]


def test_paypal_hosted_captcha_bypass_function_source_builds_stable_cleanup_script():
    script = payment_checkout_browser.paypal_hosted_captcha_bypass_function_source()

    assert "__AUTOTOKEN_PAYPAL_HOSTED_CAPTCHA_BYPASS__" in script
    assert "autotoken-paypal-hosted-captcha-bypass-style" in script
    assert "#captcha-standalone" in script
    assert ".captcha-overlay" in script
    assert ".captcha-container" in script
    assert "MutationObserver" in script
    assert "window.setInterval" in script
    assert "removed: removeArtifacts()" in script


def test_paypal_hosted_captcha_bypass_function_source_json_escapes_custom_selectors():
    script = payment_checkout_browser.paypal_hosted_captcha_bypass_function_source(('iframe[title="captcha"]',))

    assert '"iframe[title=\\"captcha\\"]"' in script


def test_dismiss_address_autocomplete_blurs_locator_and_presses_escape():
    class FakeLocator:
        def __init__(self):
            self.evaluated = False
            self.pressed = []

        def evaluate(self, script, timeout=None):
            self.evaluated = True

        def press(self, key, timeout=None):
            self.pressed.append(key)

    locator = FakeLocator()
    api = FakeApi(FakePage())

    payment_checkout_browser.dismiss_address_autocomplete(api, locator, sleep=lambda seconds: None)

    assert locator.evaluated is True
    assert locator.pressed == ["Escape"]
    assert api.page.keyboard.pressed == ["Escape"]
    assert api._address_autocomplete_dismiss_logged is True


def test_click_first_visible_scrolls_and_clicks_first_locator():
    class FakeLocator:
        def __init__(self, *, disabled=False, click_raises=False):
            self.disabled = disabled
            self.click_raises = click_raises
            self.scrolled = False
            self.clicked = False

        def is_disabled(self, timeout=None):
            return self.disabled

        def scroll_into_view_if_needed(self, timeout=None):
            self.scrolled = True

        def click(self, timeout=None):
            if self.click_raises:
                raise RuntimeError("click failed")
            self.clicked = True

    selectors_seen = []
    locator = FakeLocator()

    assert (
        payment_checkout_browser.click_first_visible(
            ["button"],
            visible_locator=lambda selectors, timeout: selectors_seen.append((selectors, timeout)) or locator,
            timeout_ms=1234,
        )
        is True
    )
    assert selectors_seen == [(["button"], 1234)]
    assert locator.scrolled is True
    assert locator.clicked is True
    assert (
        payment_checkout_browser.click_first_visible(
            ["button"],
            visible_locator=lambda _selectors, _timeout: FakeLocator(disabled=True),
        )
        is False
    )
    assert (
        payment_checkout_browser.click_first_visible(
            ["button"],
            visible_locator=lambda _selectors, _timeout: FakeLocator(click_raises=True),
        )
        is False
    )
    assert (
        payment_checkout_browser.click_first_visible(
            ["button"],
            visible_locator=lambda _selectors, _timeout: None,
        )
        is False
    )


def test_locator_is_checked_uses_native_attr_input_and_aria_fallbacks():
    class FakeLocator:
        def __init__(self, *, native=None, attrs=None, tag="div", checked_value=None):
            self.native = native
            self.attrs = attrs or {}
            self.tag = tag
            self.checked_value = checked_value

        def is_checked(self, timeout=None):
            if self.native is None:
                raise RuntimeError("not checkable")
            return self.native

        def get_attribute(self, name, timeout=None):
            return self.attrs.get(name)

        def evaluate(self, script, timeout=None):
            if "tagName" in script:
                return self.tag
            if "Boolean(el.checked)" in script:
                return self.checked_value
            return None

    assert payment_checkout_browser.locator_is_checked(FakeLocator(native=True)) is True
    assert (
        payment_checkout_browser.locator_is_checked(FakeLocator(attrs={"checked": ""}, tag="input", checked_value=True))
        is True
    )
    assert (
        payment_checkout_browser.locator_is_checked(
            FakeLocator(attrs={"checked": "checked"}, tag="div", checked_value=None)
        )
        is True
    )
    assert payment_checkout_browser.locator_is_checked(FakeLocator(attrs={"aria-checked": "true"})) is True
    assert payment_checkout_browser.locator_is_checked(FakeLocator(attrs={"aria-checked": "false"})) is False


def test_paypal_option_selected_prefers_attached_checked_locator_then_js_fallback():
    class FakePage:
        def __init__(self, result):
            self.result = result
            self.evaluated = []

        def evaluate(self, script):
            self.evaluated.append(script)
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    class FakeApi:
        def __init__(self, result):
            self.page = FakePage(result)

    checked_locator = object()
    assert (
        payment_checkout_browser.paypal_option_selected(
            FakeApi(False),
            state_selectors=["paypal-state"],
            attached_locator=lambda selectors, timeout: checked_locator,
            locator_checked=lambda locator: locator is checked_locator,
        )
        is True
    )

    api = FakeApi(True)
    assert (
        payment_checkout_browser.paypal_option_selected(
            api,
            state_selectors=["paypal-state"],
            attached_locator=lambda _selectors, _timeout: None,
        )
        is True
    )
    assert "payment-method-accordion-item-title-paypal" in api.page.evaluated[0]

    assert (
        payment_checkout_browser.paypal_option_selected(
            FakeApi(RuntimeError("closed")),
            state_selectors=["paypal-state"],
            attached_locator=lambda _selectors, _timeout: None,
        )
        is False
    )


def test_click_paypal_checkout_control_uses_click_first_then_locator_fallback():
    class FakeLocator:
        def __init__(self):
            self.scrolled = False
            self.checked = False

        def scroll_into_view_if_needed(self, timeout=None):
            self.scrolled = timeout

        def check(self, timeout=None, force=False):
            self.checked = (timeout, force)

        def click(self, timeout=None, force=False):
            raise RuntimeError("click should not run after check succeeds")

        def evaluate(self, script, timeout=None):
            raise RuntimeError("evaluate should not run after check succeeds")

    assert (
        payment_checkout_browser.click_paypal_checkout_control(
            FakeApi(FakePage()),
            checkout_selectors=["paypal-control"],
            state_selectors=["paypal-state"],
            click_first=lambda selectors, timeout: selectors == ["paypal-control"] and timeout == 2500,
            attached_locator=lambda _selectors, _timeout: None,
        )
        is True
    )

    locator = FakeLocator()
    assert (
        payment_checkout_browser.click_paypal_checkout_control(
            FakeApi(FakePage()),
            checkout_selectors=["paypal-control"],
            state_selectors=["paypal-state"],
            click_first=lambda _selectors, _timeout: False,
            attached_locator=lambda selectors, timeout: (
                locator if selectors == ["paypal-state"] and timeout == 400 else None
            ),
        )
        is True
    )
    assert locator.scrolled == 1200
    assert locator.checked == (1200, True)


def test_click_paypal_checkout_control_uses_page_and_frame_fallbacks():
    page_success_api = FakeApi(FakePage(evaluate_result=True))
    assert (
        payment_checkout_browser.click_paypal_checkout_control(
            page_success_api,
            checkout_selectors=["paypal-control"],
            state_selectors=["paypal-state"],
            click_first=lambda _selectors, _timeout: False,
            attached_locator=lambda _selectors, _timeout: None,
            frames=lambda _api: [],
        )
        is True
    )
    assert "paypal-accordion-item-button" in page_success_api.page.evaluated[0][0]

    class FakeEvalFrame:
        def __init__(self, result):
            self.result = result
            self.evaluated = []

        def evaluate(self, script):
            self.evaluated.append(script)
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    failed_frame = FakeEvalFrame(RuntimeError("closed"))
    success_frame = FakeEvalFrame(True)
    frame_api = FakeApi(FakePage(evaluate_result=False))
    assert (
        payment_checkout_browser.click_paypal_checkout_control(
            frame_api,
            checkout_selectors=["paypal-control"],
            state_selectors=["paypal-state"],
            click_first=lambda _selectors, _timeout: False,
            attached_locator=lambda _selectors, _timeout: None,
            frames=lambda _api: [failed_frame, success_frame],
        )
        is True
    )
    assert "paypalText" in success_frame.evaluated[0]


def test_select_paypal_option_short_circuits_for_paypal_host():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkout"))
    progress_events = []
    sleeps = []

    assert (
        payment_checkout_browser.select_paypal_option(
            api,
            paypal_host=lambda url: url.endswith("paypal.com/checkout"),
            option_selected=lambda _api: (_ for _ in ()).throw(RuntimeError("should not inspect option")),
            click_control=lambda _api: (_ for _ in ()).throw(RuntimeError("should not click")),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
            sleep=sleeps.append,
        )
        is True
    )
    assert progress_events == []
    assert sleeps == []


def test_select_paypal_option_emits_progress_for_existing_selection():
    api = FakeApi(FakePage(url="https://chatgpt.com/checkout"))
    progress_events = []

    assert (
        payment_checkout_browser.select_paypal_option(
            api,
            paypal_host=lambda _url: False,
            option_selected=lambda _api: True,
            click_control=lambda _api: (_ for _ in ()).throw(RuntimeError("should not click")),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
        )
        is True
    )
    assert progress_events == [{"stage": "paypal_option_selected", "url": "https://chatgpt.com/checkout"}]


def test_select_paypal_option_retries_click_until_selected():
    api = FakeApi(FakePage(url="https://chatgpt.com/checkout"))
    progress_events = []
    sleeps = []
    click_count = 0
    selected_checks = 0

    def option_selected(_api):
        nonlocal selected_checks
        selected_checks += 1
        return selected_checks >= 3

    def click_control(_api):
        nonlocal click_count
        click_count += 1
        return False

    assert (
        payment_checkout_browser.select_paypal_option(
            api,
            paypal_host=lambda _url: False,
            option_selected=option_selected,
            click_control=click_control,
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
            sleep=sleeps.append,
            attempts=3,
        )
        is True
    )
    assert click_count == 2
    assert selected_checks == 3
    assert sleeps == [0.8, 0.4, 0.8]
    assert progress_events == [{"stage": "paypal_option_selected", "url": "https://chatgpt.com/checkout"}]


def test_wait_paypal_checkout_interactive_accepts_visible_paypal_or_submit_controls():
    api = FakeApi(FakePage())
    calls = []

    def visible_locator(selectors, timeout):
        calls.append((selectors, timeout))
        return selectors == ["paypal-control"]

    assert (
        payment_checkout_browser.wait_paypal_checkout_interactive(
            api,
            paypal_selectors=["paypal-control"],
            submit_selectors=["submit-control"],
            visible_locator=visible_locator,
            body_excerpt=lambda _api, _limit: "",
        )
        is True
    )
    assert calls == [(["paypal-control"], 800)]

    calls = []

    def submit_visible_locator(selectors, timeout):
        calls.append((selectors, timeout))
        return selectors == ["submit-control"]

    assert (
        payment_checkout_browser.wait_paypal_checkout_interactive(
            api,
            paypal_selectors=["paypal-control"],
            submit_selectors=["submit-control"],
            visible_locator=submit_visible_locator,
            body_excerpt=lambda _api, _limit: "",
        )
        is True
    )
    assert calls == [(["paypal-control"], 800), (["submit-control"], 500)]


def test_wait_paypal_checkout_interactive_accepts_payment_body_hints():
    api = FakeApi(FakePage(body="Payment details are loading"))

    assert (
        payment_checkout_browser.wait_paypal_checkout_interactive(
            api,
            paypal_selectors=["paypal-control"],
            submit_selectors=["submit-control"],
            visible_locator=lambda _selectors, _timeout: None,
            body_excerpt=lambda api, limit: api.page.body[:limit],
        )
        is True
    )


def test_wait_paypal_checkout_interactive_times_out_with_fallback_sleep_and_log():
    class RaisingWaitPage(FakePage):
        def wait_for_timeout(self, timeout):
            super().wait_for_timeout(timeout)
            raise RuntimeError("closed")

    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    api = FakeApi(RaisingWaitPage(url="https://chatgpt.com/checkout", body="still loading"))
    logger = FakeLogger()
    sleeps = []
    times = iter([0, 1, 6])

    assert (
        payment_checkout_browser.wait_paypal_checkout_interactive(
            api,
            paypal_selectors=["paypal-control"],
            submit_selectors=["submit-control"],
            visible_locator=lambda _selectors, _timeout: None,
            body_excerpt=lambda api, limit: api.page.body[:limit],
            logger=logger,
            url_summary=lambda url: f"summary:{url}",
            now=lambda: next(times),
            sleep=sleeps.append,
            timeout_seconds=1,
        )
        is False
    )
    assert api.page.waited == [1000]
    assert sleeps == [1.0]
    assert logger.messages == [
        (
            "[paypal_bind_executor] checkout page not interactive: url=%s body=%s",
            ("summary:https://chatgpt.com/checkout", "still loading"),
        )
    ]


def test_inspect_paypal_page_marks_login_phase_and_captcha_bypass():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup", body="Welcome back"))
    email_locator = object()
    password_locator = object()
    captcha_calls = []

    def visible_locator(selectors, _timeout):
        if selectors == ["email"]:
            return email_locator
        if selectors == ["password"]:
            return password_locator
        return None

    state = payment_checkout_browser.inspect_paypal_page(
        api,
        paypal_host=lambda _url: True,
        ensure_captcha_bypass=lambda value: captcha_calls.append(value) or True,
        body_excerpt=lambda api, limit: api.page.body[:limit],
        visible_locator=visible_locator,
        has_phone_rejected_prompt=lambda _api: False,
        has_otp_inputs=lambda _api: False,
        phone_rejected_text_hint=lambda _text: False,
        card_rejected_text_hint=lambda _text: False,
        signup_registration_text_hint=lambda _text: False,
        signup_otp_text_hint=lambda _text, *, loose=False: False,
        login_text_hint=lambda _text: False,
        passkey_text_hint=lambda _text: False,
        approve_text_hint=lambda _text: False,
        email_selectors=["email"],
        password_selectors=["password"],
        approve_selectors=["approve"],
        prompt_selectors=["prompt"],
        create_account_selectors=["create"],
        phone_selectors=["phone"],
        card_selectors=["card"],
    )

    assert captcha_calls == [api]
    assert state["needs_login"] is True
    assert state["login_phase"] == "login_combined"
    assert state["email_locator"] is email_locator
    assert state["password_locator"] is password_locator


def test_inspect_paypal_page_marks_phone_and_card_rejection_hints():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup", body="Create an account"))

    state = payment_checkout_browser.inspect_paypal_page(
        api,
        paypal_host=lambda _url: True,
        ensure_captcha_bypass=lambda _api: True,
        body_excerpt=lambda api, limit: api.page.body[:limit],
        visible_locator=lambda _selectors, _timeout: None,
        has_phone_rejected_prompt=lambda _api: True,
        has_otp_inputs=lambda _api: False,
        phone_rejected_text_hint=lambda text: "Try a different phone number" in text,
        card_rejected_text_hint=lambda _text: True,
        signup_registration_text_hint=lambda _text: False,
        signup_otp_text_hint=lambda _text, *, loose=False: False,
        login_text_hint=lambda _text: False,
        passkey_text_hint=lambda _text: False,
        approve_text_hint=lambda _text: False,
        email_selectors=["email"],
        password_selectors=["password"],
        approve_selectors=["approve"],
        prompt_selectors=["prompt"],
        create_account_selectors=["create"],
        phone_selectors=["phone"],
        card_selectors=["card"],
    )

    assert "Try a different phone number" in state["body_text"]
    assert state["card_rejected"] is True
    assert state["registration_ready"] is True


def test_inspect_paypal_page_marks_otp_prompt_over_registration_inputs():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup", body="Card number Enter your code"))

    def visible_locator(selectors, _timeout):
        return object() if selectors in (["phone"], ["card"]) else None

    state = payment_checkout_browser.inspect_paypal_page(
        api,
        paypal_host=lambda _url: True,
        ensure_captcha_bypass=lambda _api: True,
        body_excerpt=lambda api, limit: api.page.body[:limit],
        visible_locator=visible_locator,
        has_phone_rejected_prompt=lambda _api: False,
        has_otp_inputs=lambda _api: False,
        phone_rejected_text_hint=lambda _text: False,
        card_rejected_text_hint=lambda _text: False,
        signup_registration_text_hint=lambda _text: True,
        signup_otp_text_hint=lambda text, *, loose=False: loose and "Enter your code" in text,
        login_text_hint=lambda _text: False,
        passkey_text_hint=lambda _text: False,
        approve_text_hint=lambda _text: False,
        email_selectors=["email"],
        password_selectors=["password"],
        approve_selectors=["approve"],
        prompt_selectors=["prompt"],
        create_account_selectors=["create"],
        phone_selectors=["phone"],
        card_selectors=["card"],
    )

    assert state["needs_otp"] is True
    assert state["otp_inputs_ready"] is True
    assert state["registration_text_hint"] is True
    assert state["registration_ready"] is False


def test_dismiss_paypal_prompts_emits_progress_when_clicked():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkout"))
    progress_events = []
    captured = {}

    assert (
        payment_checkout_browser.dismiss_paypal_prompts(
            api,
            prompt_selectors=["dismiss"],
            click_first=lambda selectors, timeout: (
                captured.update({"selectors": selectors, "timeout": timeout}) or True
            ),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
        )
        is True
    )
    assert captured == {"selectors": ["dismiss"], "timeout": 1500}
    assert progress_events == [{"stage": "paypal_prompt_dismissed", "url": "https://www.paypal.com/checkout"}]

    assert (
        payment_checkout_browser.dismiss_paypal_prompts(
            api,
            prompt_selectors=["dismiss"],
            click_first=lambda _selectors, _timeout: False,
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
        )
        is False
    )


def test_paypal_signup_registration_form_visible_uses_text_then_visible_fields():
    api = FakeApi(FakePage(body="Card number Billing address"))

    assert (
        payment_checkout_browser.paypal_signup_registration_form_visible(
            api,
            body_excerpt=lambda api, limit: api.page.body[:limit],
            text_visible=lambda text: "Billing address" in text,
            visible_locator=lambda _selectors, _timeout: (_ for _ in ()).throw(
                RuntimeError("should not inspect fields")
            ),
            field_selector_groups=(["phone"], ["card"], ["expiry"]),
        )
        is True
    )

    visible_groups = {("phone",), ("card",)}

    assert (
        payment_checkout_browser.paypal_signup_registration_form_visible(
            api,
            body_excerpt=lambda _api, _limit: "",
            text_visible=lambda _text: False,
            visible_locator=lambda selectors, timeout: (
                object() if tuple(selectors) in visible_groups and timeout == 250 else None
            ),
            field_selector_groups=(["phone"], ["card"], ["expiry"]),
        )
        is True
    )

    assert (
        payment_checkout_browser.paypal_signup_registration_form_visible(
            api,
            body_excerpt=lambda _api, _limit: "",
            text_visible=lambda _text: False,
            visible_locator=lambda selectors, _timeout: object() if selectors == ["phone"] else None,
            field_selector_groups=(["phone"], ["card"], ["expiry"]),
        )
        is False
    )

    assert (
        payment_checkout_browser.paypal_signup_registration_form_visible(
            api,
            body_excerpt=lambda _api, _limit: "",
            text_visible=lambda _text: False,
            visible_locator=lambda _selectors, _timeout: (_ for _ in ()).throw(RuntimeError("closed")),
            field_selector_groups=(["phone"], ["card"], ["expiry"]),
        )
        is False
    )


def test_click_paypal_create_account_emits_progress_when_clicked():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    progress_events = []
    captured = {}

    assert (
        payment_checkout_browser.click_paypal_create_account(
            api,
            create_account_selectors=["create"],
            click_first=lambda selectors, timeout: (
                captured.update({"selectors": selectors, "timeout": timeout}) or True
            ),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
        )
        is True
    )
    assert captured == {"selectors": ["create"], "timeout": 2000}
    assert progress_events == [{"stage": "paypal_create_account", "url": "https://www.paypal.com/checkoutweb/signup"}]

    assert (
        payment_checkout_browser.click_paypal_create_account(
            api,
            create_account_selectors=["create"],
            click_first=lambda _selectors, _timeout: False,
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
        )
        is False
    )


def test_maybe_enter_paypal_signup_from_login_uses_click_or_ba_entry():
    api = FakeApi(FakePage(url="https://www.paypal.com/signin"))
    sleeps = []
    click_calls = []
    goto_calls = []

    clicked = payment_checkout_browser.maybe_enter_paypal_signup_from_login(
        api,
        state={"needs_login": True, "create_account_ready": True, "ba_token": "BA-STATE"},
        signup_submitted=False,
        signup_email_submitted=False,
        ba_token="",
        country="JP",
        lang="ja",
        click_create_account=lambda target: click_calls.append(target) or True,
        goto_create_account_entry=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("goto should not run after click")
        ),
        sleep=sleeps.append,
    )
    redirected = payment_checkout_browser.maybe_enter_paypal_signup_from_login(
        api,
        state={"needs_login": True, "ba_token": "BA-STATE"},
        signup_submitted=False,
        signup_email_submitted=False,
        ba_token="BA-ARG",
        country="JP",
        lang="ja",
        click_create_account=lambda _api: False,
        goto_create_account_entry=lambda target, **kwargs: goto_calls.append((target, kwargs)) or True,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should only run for clicked entry")),
    )

    assert clicked == (True, "", True)
    assert click_calls == [api]
    assert sleeps == [2.0]
    assert redirected == (True, "", True)
    assert goto_calls == [(api, {"ba_token": "BA-ARG", "country": "JP", "lang": "ja"})]


def test_maybe_enter_paypal_signup_from_login_skips_non_login_or_unhandled_entry():
    api = FakeApi(FakePage(url="https://www.paypal.com/signin"))

    skipped = payment_checkout_browser.maybe_enter_paypal_signup_from_login(
        api,
        state={"needs_login": False},
        signup_submitted=False,
        signup_email_submitted=False,
        ba_token="",
        country="US",
        lang="en",
        click_create_account=lambda _api: (_ for _ in ()).throw(RuntimeError("should not click")),
        goto_create_account_entry=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("should not goto")),
    )
    unhandled = payment_checkout_browser.maybe_enter_paypal_signup_from_login(
        api,
        state={"needs_login": True, "ba_token": "BA-STATE"},
        signup_submitted=False,
        signup_email_submitted=False,
        ba_token="",
        country="US",
        lang="en",
        click_create_account=lambda _api: False,
        goto_create_account_entry=lambda _target, **kwargs: (
            kwargs
            == {
                "ba_token": "BA-MISSING",
                "country": "US",
                "lang": "en",
            }
        ),
    )

    assert skipped is None
    assert unhandled == (True, "", False)


def test_handle_paypal_signup_needs_login_redirect_skips_when_not_login():
    result = payment_checkout_browser.handle_paypal_signup_needs_login_redirect(
        FakeApi(FakePage(url="https://www.paypal.com/signin")),
        state={},
        signup_login_redirect_count=0,
        max_redirects=3,
        ba_token="BA-TOKEN",
        country="JP",
        lang="ja",
        goto_create_account_entry=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("goto should not run")
        ),
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result is None


def test_handle_paypal_signup_needs_login_redirect_returns_continue_and_resets_signup_state():
    api = FakeApi(FakePage(url="https://www.paypal.com/signin"))
    goto_calls = []
    sleeps = []
    progress_events = []
    on_progress = progress_events.append

    result = payment_checkout_browser.handle_paypal_signup_needs_login_redirect(
        api,
        state={"needs_login": True},
        signup_login_redirect_count=2,
        max_redirects=3,
        ba_token="BA-TOKEN",
        country="JP",
        lang="ja",
        goto_create_account_entry=lambda target, **kwargs: goto_calls.append((target, kwargs)) or True,
        on_progress=on_progress,
        sleep_after_redirect_seconds=1.5,
        sleep=sleeps.append,
    )

    assert result == {
        "action": "continue",
        "signup_login_redirect_count": 3,
        "signup_email_submitted": False,
        "signup_email_submitted_at": 0.0,
        "signup_form_submitted": False,
        "signup_submitted_at": 0.0,
    }
    assert goto_calls == [
        (
            api,
            {
                "ba_token": "BA-TOKEN",
                "country": "JP",
                "lang": "ja",
                "on_progress": on_progress,
            },
        )
    ]
    assert sleeps == [1.5]


def test_handle_paypal_signup_needs_login_redirect_returns_failure_after_limit_or_failed_goto():
    failure = payment_checkout_browser.handle_paypal_signup_needs_login_redirect(
        FakeApi(FakePage(url="https://www.paypal.com/signin")),
        state={"needs_login": True},
        signup_login_redirect_count=3,
        max_redirects=3,
        ba_token="BA-TOKEN",
        country="JP",
        lang="ja",
        goto_create_account_entry=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("goto should not run after limit")
        ),
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )
    failed_goto = payment_checkout_browser.handle_paypal_signup_needs_login_redirect(
        FakeApi(FakePage(url="https://www.paypal.com/signin")),
        state={"needs_login": True},
        signup_login_redirect_count=0,
        max_redirects=3,
        ba_token="BA-TOKEN",
        country="JP",
        lang="ja",
        goto_create_account_entry=lambda *_args, **_kwargs: False,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert failure == {
        "action": "failed",
        "screenshot_label": "paypal-signup-login-page",
        "message": "PayPal 仍停留在已有账号登录页，注册模式已停止提交登录表单",
    }
    assert failed_goto == failure


def test_maybe_dismiss_paypal_passkey_prompt_skips_when_absent_or_otp_needed():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkout"))

    for state in [{}, {"has_passkey_prompt": True, "needs_otp": True}]:
        assert (
            payment_checkout_browser.maybe_dismiss_paypal_passkey_prompt(
                api,
                state=state,
                dismiss_prompts=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("dismiss should not run")
                ),
                sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
            )
            is False
        )


def test_maybe_dismiss_paypal_passkey_prompt_returns_false_when_dismiss_fails():
    assert (
        payment_checkout_browser.maybe_dismiss_paypal_passkey_prompt(
            FakeApi(FakePage(url="https://www.paypal.com/checkout")),
            state={"has_passkey_prompt": True},
            dismiss_prompts=lambda *_args, **_kwargs: False,
            sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
        )
        is False
    )


def test_maybe_dismiss_paypal_passkey_prompt_dismisses_and_waits():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkout"))
    progress_events = []
    on_progress = progress_events.append
    dismiss_calls = []
    sleeps = []

    assert (
        payment_checkout_browser.maybe_dismiss_paypal_passkey_prompt(
            api,
            state={"has_passkey_prompt": True},
            dismiss_prompts=lambda target, **kwargs: dismiss_calls.append((target, kwargs)) or True,
            on_progress=on_progress,
            sleep=sleeps.append,
        )
        is True
    )
    assert dismiss_calls == [(api, {"on_progress": on_progress})]
    assert sleeps == [1.2]


def test_maybe_click_paypal_signup_create_account_ready_clicks_and_waits():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    sleeps = []
    clicks = []

    result = payment_checkout_browser.maybe_click_paypal_signup_create_account_ready(
        api,
        state={"create_account_ready": True},
        click_create_account=lambda target: clicks.append(target) or True,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert clicks == [api]
    assert sleeps == [2.0]


def test_maybe_click_paypal_signup_create_account_ready_skips_blocking_states_or_failed_click():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    calls = []

    for state in [
        {},
        {"create_account_ready": True, "registration_ready": True},
        {"create_account_ready": True, "registration_text_hint": True},
        {"create_account_ready": True, "needs_otp": True},
    ]:
        result = payment_checkout_browser.maybe_click_paypal_signup_create_account_ready(
            api,
            state=state,
            click_create_account=lambda _api: calls.append("click") or True,
            sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
        )
        assert result is None

    failed_click = payment_checkout_browser.maybe_click_paypal_signup_create_account_ready(
        api,
        state={"create_account_ready": True},
        click_create_account=lambda _api: calls.append("click") or False,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert failed_click is None
    assert calls == ["click"]


def test_seed_paypal_signup_authorize_state_writes_loop_state_and_preserves_phone_key_set():
    submitted_phone_keys = {"12025550123"}
    state = {"existing": "kept"}

    result = payment_checkout_browser.seed_paypal_signup_authorize_state(
        state,
        signup_email_submitted=True,
        signup_email_submitted_at=12.5,
        signup_form_submitted=True,
        signup_submitted_at=20.5,
        submitted_phone_keys=submitted_phone_keys,
        phone_only_retry=True,
        card_retry_count=2,
        otp_phone_lock_key="otp-lock",
    )

    assert result is state
    assert state == {
        "existing": "kept",
        "signup_email_submitted": True,
        "signup_email_submitted_at": 12.5,
        "signup_submitted": True,
        "signup_submitted_at": 20.5,
        "submitted_phone_keys": submitted_phone_keys,
        "phone_only_retry": True,
        "card_retry_count": 2,
        "otp_phone_lock_key": "otp-lock",
    }
    assert state["submitted_phone_keys"] is submitted_phone_keys


def test_sync_paypal_signup_authorize_state_tracks_new_email_and_form_submission():
    state = {
        "signup_email_submitted": True,
        "signup_email_submitted_at": 0,
        "signup_submitted": True,
        "signup_submitted_at": 0,
        "phone_only_retry": True,
        "card_retry_count": 2,
        "otp_phone_lock_key": "otp-lock",
    }

    result = payment_checkout_browser.sync_paypal_signup_authorize_state(
        state,
        signup_email_submitted=False,
        signup_email_submitted_at=0.0,
        signup_form_submitted=False,
        signup_submitted_at=0.0,
        card_retry_count=1,
        now=lambda: 1234.5,
    )

    assert result == {
        "signup_email_submitted": True,
        "signup_email_submitted_at": 1234.5,
        "signup_form_submitted": True,
        "signup_submitted_at": 1234.5,
        "phone_only_retry": True,
        "card_retry_count": 2,
        "otp_phone_lock_key": "otp-lock",
    }


def test_sync_paypal_signup_authorize_state_updates_existing_email_timestamp_and_form_timestamp():
    result = payment_checkout_browser.sync_paypal_signup_authorize_state(
        {
            "signup_email_submitted": True,
            "signup_email_submitted_at": 222.0,
            "signup_submitted_at": 333.0,
        },
        signup_email_submitted=True,
        signup_email_submitted_at=111.0,
        signup_form_submitted=True,
        signup_submitted_at=100.0,
        card_retry_count=4,
        now=lambda: (_ for _ in ()).throw(AssertionError("now should not run")),
    )

    assert result["signup_email_submitted"] is True
    assert result["signup_email_submitted_at"] == 222.0
    assert result["signup_form_submitted"] is True
    assert result["signup_submitted_at"] == 333.0
    assert result["card_retry_count"] == 4


def test_sync_paypal_signup_authorize_state_resets_email_when_state_clears_after_reload():
    result = payment_checkout_browser.sync_paypal_signup_authorize_state(
        {"signup_email_submitted": False},
        signup_email_submitted=True,
        signup_email_submitted_at=111.0,
        signup_form_submitted=False,
        signup_submitted_at=0.0,
        card_retry_count=3,
    )

    assert result["signup_email_submitted"] is False
    assert result["signup_email_submitted_at"] == 0.0
    assert result["signup_form_submitted"] is False
    assert result["signup_submitted_at"] == 0.0
    assert result["phone_only_retry"] is False
    assert result["card_retry_count"] == 3
    assert result["otp_phone_lock_key"] == ""


def test_paypal_signup_authorize_state_values_coerces_state_tuple():
    assert payment_checkout_browser.paypal_signup_authorize_state_values(
        {
            "signup_email_submitted": 1,
            "signup_email_submitted_at": "12.5",
            "signup_form_submitted": "",
            "signup_submitted_at": "20.5",
            "phone_only_retry": "yes",
            "card_retry_count": "3",
            "otp_phone_lock_key": 12345,
        }
    ) == (True, 12.5, False, 20.5, True, 3, "12345")


def test_merge_paypal_inspected_state_preserves_recover_keys_and_sets_ba_token():
    previous_state = {
        "_email_stuck_recover_count": 2,
        "_email_reload_cycle_count": 1,
        "_email_first_submitted_at": 100.0,
        "_fill_retry_count": 3,
        "registration_ready": True,
    }
    inspected_state = {
        "body_text": "fresh",
        "_email_stuck_recover_count": 0,
        "_fill_retry_count": 0,
    }

    result = payment_checkout_browser.merge_paypal_inspected_state(
        previous_state,
        inspected_state,
        ba_token="BA-TOKEN",
    )

    assert result == {
        "body_text": "fresh",
        "_email_stuck_recover_count": 2,
        "_email_reload_cycle_count": 1,
        "_email_first_submitted_at": 100.0,
        "_fill_retry_count": 3,
        "ba_token": "BA-TOKEN",
    }
    assert inspected_state["_email_stuck_recover_count"] == 0


def test_merge_paypal_inspected_state_handles_missing_previous_state_and_empty_ba_token():
    result = payment_checkout_browser.merge_paypal_inspected_state(
        None,
        {"body_text": "fresh"},
        ba_token="",
    )

    assert result == {"body_text": "fresh"}


def test_paypal_signup_email_step_state_detects_email_step_without_timeout():
    email_locator = object()
    state = {"email_locator": email_locator}

    result = payment_checkout_browser.paypal_signup_email_step_state(
        state,
        signup_email_submitted=False,
        wait_timeout_seconds=120,
        now=lambda: 1000.0,
    )

    assert result == {
        "is_email_step": True,
        "is_blank_after_email": False,
        "submitted_at": 0.0,
        "first_submitted_at": 0.0,
        "timeout_result": None,
    }
    assert state == {"email_locator": email_locator}


def test_paypal_signup_email_step_state_tracks_blank_after_email_first_submit_time():
    state = {
        "signup_email_submitted_at": 100.0,
    }

    result = payment_checkout_browser.paypal_signup_email_step_state(
        state,
        signup_email_submitted=True,
        wait_timeout_seconds=120,
        now=lambda: 150.0,
    )

    assert result["is_email_step"] is False
    assert result["is_blank_after_email"] is True
    assert result["submitted_at"] == 100.0
    assert result["first_submitted_at"] == 100.0
    assert result["timeout_result"] is None
    assert state["_email_first_submitted_at"] == 100.0


def test_paypal_signup_email_step_state_returns_timeout_from_first_submit_time():
    state = {
        "email_locator": object(),
        "signup_email_submitted_at": 200.0,
        "_email_first_submitted_at": 100.0,
    }

    result = payment_checkout_browser.paypal_signup_email_step_state(
        state,
        signup_email_submitted=True,
        wait_timeout_seconds=120,
        now=lambda: 221.0,
    )

    assert result["is_email_step"] is True
    assert result["is_blank_after_email"] is False
    assert result["submitted_at"] == 200.0
    assert result["first_submitted_at"] == 100.0
    assert result["timeout_result"] == (False, "等待 PayPal 注册表单加载超时", False)
    assert state["_email_first_submitted_at"] == 100.0


def test_paypal_signup_email_step_state_skips_registration_login_and_otp_states():
    blank_result = payment_checkout_browser.paypal_signup_email_step_state(
        {},
        signup_email_submitted=True,
        wait_timeout_seconds=120,
        now=lambda: 300.0,
    )

    assert blank_result["is_email_step"] is False
    assert blank_result["is_blank_after_email"] is True
    assert blank_result["timeout_result"] is None

    for state in [
        {"email_locator": object(), "registration_ready": True},
        {"email_locator": object(), "registration_text_hint": True},
        {"signup_email_submitted_at": 100.0, "needs_login": True},
        {"signup_email_submitted_at": 100.0, "needs_otp": True},
        {"signup_email_submitted_at": 100.0, "approve_ready": True},
    ]:
        result = payment_checkout_browser.paypal_signup_email_step_state(
            state,
            signup_email_submitted=True,
            wait_timeout_seconds=120,
            now=lambda: 300.0,
        )
        assert result["is_email_step"] is False
        assert result["is_blank_after_email"] is False
        assert result["timeout_result"] is None
        assert "_email_first_submitted_at" not in state


def test_recover_paypal_signup_email_step_returns_none_before_delay():
    state = {"_email_stuck_recover_count": 0}

    result = payment_checkout_browser.recover_paypal_signup_email_step(
        FakeApi(FakePage()),
        signup_profile={"email": "demo@example.com"},
        state=state,
        submitted_at=100.0,
        first_submitted_at=100.0,
        stuck_recover_delay_seconds=30,
        recover_email_spinner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recover should not run")),
        progress_event=lambda stage, message="", **extra: {"stage": stage, "message": message, **extra},
        now=lambda: 120.0,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result is None
    assert state == {"_email_stuck_recover_count": 0}


def test_recover_paypal_signup_email_step_runs_js_attempt_and_keeps_recovered_state():
    state = {"signup_email_submitted": True, "signup_email_submitted_at": 100.0}
    recover_calls = []
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.recover_paypal_signup_email_step(
        FakeApi(FakePage()),
        signup_profile={"email": " demo@example.com "},
        state=state,
        submitted_at=100.0,
        first_submitted_at=100.0,
        stuck_recover_delay_seconds=30,
        recover_email_spinner=lambda api, email: recover_calls.append((api, email)) or {"recovered": True},
        progress_event=lambda stage, message="", **extra: {"stage": stage, "message": message, **extra},
        on_progress=progress_events.append,
        now=lambda: 140.0,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert state == {
        "signup_email_submitted": True,
        "signup_email_submitted_at": 100.0,
        "_email_stuck_recover_count": 1,
    }
    assert recover_calls[0][1] == "demo@example.com"
    assert progress_events == [
        {
            "stage": "paypal_signup_email_reload",
            "message": "邮箱提交后页面卡住，正在 JS 恢复 (1/1)",
        }
    ]
    assert sleeps == [2.0]


def test_recover_paypal_signup_email_step_resets_email_state_when_js_attempt_fails():
    state = {"signup_email_submitted": True, "signup_email_submitted_at": 100.0}

    result = payment_checkout_browser.recover_paypal_signup_email_step(
        FakeApi(FakePage()),
        signup_profile={"email": "demo@example.com"},
        state=state,
        submitted_at=100.0,
        first_submitted_at=100.0,
        stuck_recover_delay_seconds=30,
        recover_email_spinner=lambda _api, _email: {"recovered": False},
        progress_event=lambda stage, message="", **extra: {"stage": stage, "message": message, **extra},
        now=lambda: 140.0,
        sleep=lambda _seconds: None,
    )

    assert result == (True, "", True)
    assert state["signup_email_submitted"] is False
    assert state["signup_email_submitted_at"] == 0
    assert state["_email_stuck_recover_count"] == 1


def test_recover_paypal_signup_email_step_reloads_after_js_attempts_exhausted():
    class ReloadPage(FakePage):
        def __init__(self):
            super().__init__(url="https://www.paypal.com/pay")
            self.reloads = []

        def reload(self, **kwargs):
            self.reloads.append(kwargs)

    page = ReloadPage()
    state = {
        "_email_stuck_recover_count": 1,
        "_email_reload_cycle_count": 1,
        "_email_first_submitted_at": 100.0,
        "signup_email_submitted": True,
        "signup_email_submitted_at": 130.0,
        "_fill_retry_count": 2,
    }
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.recover_paypal_signup_email_step(
        FakeApi(page),
        signup_profile={"email": "demo@example.com"},
        state=state,
        submitted_at=130.0,
        first_submitted_at=100.0,
        stuck_recover_delay_seconds=30,
        recover_email_spinner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recover should not run after js attempts exhausted")
        ),
        progress_event=lambda stage, message="", **extra: {"stage": stage, "message": message, **extra},
        on_progress=progress_events.append,
        now=lambda: 170.0,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert state == {
        "_email_stuck_recover_count": 0,
        "_email_reload_cycle_count": 2,
        "_email_first_submitted_at": 0,
        "signup_email_submitted": False,
        "signup_email_submitted_at": 0,
        "_fill_retry_count": 0,
    }
    assert page.reloads == [{"wait_until": "domcontentloaded", "timeout": 30000}]
    assert progress_events == [
        {
            "stage": "paypal_signup_email_reload",
            "message": "邮箱提交后 SPA 死锁，正在刷新页面重试 (第 2/3 轮)",
        }
    ]
    assert sleeps == [3.0]


def test_recover_paypal_signup_unhandled_email_stuck_returns_none_for_visible_state():
    result = payment_checkout_browser.recover_paypal_signup_unhandled_email_stuck(
        FakeApi(FakePage()),
        signup_profile={"email": "demo@example.com"},
        state={"email_locator": object()},
        signup_email_submitted=True,
        signup_email_submitted_at=100.0,
        current_url="https://www.paypal.com/pay",
        wait_timeout_seconds=120,
        stuck_recover_delay_seconds=30,
        recover_email_spinner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recover should not run")),
        progress_event=lambda stage, message="", **extra: {"stage": stage, "message": message, **extra},
        now=lambda: 140.0,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result is None


def test_recover_paypal_signup_unhandled_email_stuck_returns_timeout_action():
    result = payment_checkout_browser.recover_paypal_signup_unhandled_email_stuck(
        FakeApi(FakePage()),
        signup_profile={"email": "demo@example.com"},
        state={"_email_first_submitted_at": 100.0},
        signup_email_submitted=True,
        signup_email_submitted_at=150.0,
        current_url="https://www.paypal.com/pay",
        wait_timeout_seconds=120,
        stuck_recover_delay_seconds=30,
        recover_email_spinner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recover should not run")),
        progress_event=lambda stage, message="", **extra: {"stage": stage, "message": message, **extra},
        now=lambda: 221.0,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == {
        "action": "failed",
        "screenshot_label": "paypal-signup-email-timeout",
        "message": "等待 PayPal 注册表单加载超时",
    }


def test_recover_paypal_signup_unhandled_email_stuck_js_failure_resets_outer_email_state():
    state = {"signup_email_submitted": True, "signup_email_submitted_at": 100.0}
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.recover_paypal_signup_unhandled_email_stuck(
        FakeApi(FakePage()),
        signup_profile={"email": " demo@example.com "},
        state=state,
        signup_email_submitted=True,
        signup_email_submitted_at=100.0,
        current_url="https://www.paypal.com/pay",
        wait_timeout_seconds=120,
        stuck_recover_delay_seconds=30,
        recover_email_spinner=lambda _api, email: {"recovered": False, "email": email},
        progress_event=lambda stage, message="", **extra: {"stage": stage, "message": message, **extra},
        on_progress=progress_events.append,
        now=lambda: 140.0,
        sleep=sleeps.append,
    )

    assert result == {
        "action": "continue",
        "signup_email_submitted": False,
        "signup_email_submitted_at": 0.0,
    }
    assert state["signup_email_submitted"] is False
    assert state["signup_email_submitted_at"] == 0
    assert state["_email_stuck_recover_count"] == 1
    assert progress_events == [
        {
            "stage": "paypal_signup_email_reload",
            "message": "邮箱提交后页面卡住（无表单元素），JS 恢复 (1/1)",
        }
    ]
    assert sleeps == [2.0]


def test_recover_paypal_signup_unhandled_email_stuck_reloads_after_js_attempts_exhausted():
    class ReloadPage(FakePage):
        def __init__(self):
            super().__init__(url="https://www.paypal.com/pay")
            self.reloads = []

        def reload(self, **kwargs):
            self.reloads.append(kwargs)

    page = ReloadPage()
    state = {
        "_email_stuck_recover_count": 1,
        "_email_reload_cycle_count": 1,
        "_email_first_submitted_at": 100.0,
        "signup_email_submitted": True,
        "signup_email_submitted_at": 130.0,
        "_fill_retry_count": 2,
    }
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.recover_paypal_signup_unhandled_email_stuck(
        FakeApi(page),
        signup_profile={"email": "demo@example.com"},
        state=state,
        signup_email_submitted=True,
        signup_email_submitted_at=130.0,
        current_url="https://www.paypal.com/pay",
        wait_timeout_seconds=120,
        stuck_recover_delay_seconds=30,
        recover_email_spinner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recover should not run after js attempts exhausted")
        ),
        progress_event=lambda stage, message="", **extra: {"stage": stage, "message": message, **extra},
        on_progress=progress_events.append,
        now=lambda: 170.0,
        sleep=sleeps.append,
    )

    assert result == {
        "action": "continue",
        "signup_email_submitted": False,
        "signup_email_submitted_at": 0.0,
    }
    assert state == {
        "_email_stuck_recover_count": 0,
        "_email_reload_cycle_count": 2,
        "_email_first_submitted_at": 0,
        "signup_email_submitted": False,
        "signup_email_submitted_at": 0,
        "_fill_retry_count": 0,
    }
    assert page.reloads == [{"wait_until": "domcontentloaded", "timeout": 30000}]
    assert progress_events == [
        {
            "stage": "paypal_signup_email_reload",
            "message": "SPA 死锁，正在刷新页面重试 (第 2/3 轮)",
        }
    ]
    assert sleeps == [3.0]


def test_continue_paypal_signup_email_step_waits_when_email_already_submitted():
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.continue_paypal_signup_email_step(
        FakeApi(FakePage()),
        signup_profile={"email": "demo@example.com"},
        state={"signup_email_submitted": True},
        current_url="https://www.paypal.com/pay",
        signup_email_submitted=True,
        is_blank_after_email=False,
        submit_email_step=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("email submit should not rerun")
        ),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert progress_events == [
        {
            "stage": "paypal_wait_signup_form",
            "url": "https://www.paypal.com/pay",
            "email": "demo@example.com",
        }
    ]
    assert sleeps == [1.5]


def test_continue_paypal_signup_email_step_waits_for_blank_after_email_without_progress():
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.continue_paypal_signup_email_step(
        FakeApi(FakePage()),
        signup_profile={"email": "demo@example.com"},
        state={},
        current_url="https://www.paypal.com/pay",
        signup_email_submitted=False,
        is_blank_after_email=True,
        submit_email_step=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("email submit should not run on blank page")
        ),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert progress_events == []
    assert sleeps == [1.5]


def test_continue_paypal_signup_email_step_submits_and_marks_state_on_success():
    state = {"email_locator": object()}
    submit_calls = []

    result = payment_checkout_browser.continue_paypal_signup_email_step(
        FakeApi(FakePage()),
        signup_profile={"email": "demo@example.com"},
        state=state,
        current_url="https://www.paypal.com/pay",
        signup_email_submitted=False,
        is_blank_after_email=False,
        submit_email_step=lambda api, **kwargs: submit_calls.append((api, kwargs)) or (True, ""),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        now=lambda: 1234.5,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (True, "", True)
    assert submit_calls[0][1]["signup_profile"] == {"email": "demo@example.com"}
    assert submit_calls[0][1]["state"] is state
    assert state["signup_email_submitted"] is True
    assert state["signup_email_submitted_at"] == 1234.5


def test_continue_paypal_signup_email_step_does_not_mark_state_on_submit_failure():
    state = {"email_locator": object()}

    result = payment_checkout_browser.continue_paypal_signup_email_step(
        FakeApi(FakePage()),
        signup_profile={"email": "demo@example.com"},
        state=state,
        current_url="https://www.paypal.com/pay",
        signup_email_submitted=False,
        is_blank_after_email=False,
        submit_email_step=lambda *_args, **_kwargs: (False, "submit failed"),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        now=lambda: (_ for _ in ()).throw(AssertionError("now should not run")),
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (False, "submit failed", True)
    assert state == {"email_locator": state["email_locator"]}


def test_maybe_mark_paypal_signup_registration_ready_updates_state_once_visible():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    state = {}
    visible_calls = []

    assert (
        payment_checkout_browser.maybe_mark_paypal_signup_registration_ready(
            api,
            state=state,
            signup_submitted=False,
            registration_form_visible=lambda target: visible_calls.append(target) or True,
        )
        is True
    )
    assert state == {"registration_ready": True, "registration_text_hint": True}
    assert visible_calls == [api]

    assert (
        payment_checkout_browser.maybe_mark_paypal_signup_registration_ready(
            api,
            state=state,
            signup_submitted=False,
            registration_form_visible=lambda _api: (_ for _ in ()).throw(RuntimeError("already ready")),
        )
        is False
    )


def test_maybe_mark_paypal_signup_registration_ready_skips_submitted_or_invisible_state():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    submitted_state = {}
    invisible_state = {}

    assert (
        payment_checkout_browser.maybe_mark_paypal_signup_registration_ready(
            api,
            state=submitted_state,
            signup_submitted=True,
            registration_form_visible=lambda _api: (_ for _ in ()).throw(RuntimeError("submitted")),
        )
        is False
    )
    assert (
        payment_checkout_browser.maybe_mark_paypal_signup_registration_ready(
            api,
            state=invisible_state,
            signup_submitted=False,
            registration_form_visible=lambda _api: False,
        )
        is False
    )
    assert submitted_state == {}
    assert invisible_state == {}


def test_stop_before_paypal_signup_otp_sets_state_and_emits_progress():
    state = {}
    progress_events = []

    result = payment_checkout_browser.stop_before_paypal_signup_otp(
        state=state,
        signup_profile={"otp_channel": "whatsapp", "phone": "+817012345678"},
        current_url="https://www.paypal.com/checkoutweb/signup",
        progress_event=lambda stage, message="", **extra: {"stage": stage, "message": message, **extra},
        on_progress=progress_events.append,
    )

    assert result == (True, "", False)
    assert state == {"_stop_before_signup_otp": True}
    assert progress_events == [
        {
            "stage": "paypal_wait_signup_otp",
            "message": "PayPal 注册表单已提交，已在手机验证码输入前停止",
            "url": "https://www.paypal.com/checkoutweb/signup",
            "otp_channel": "whatsapp",
            "phone": "+817012345678",
        }
    ]


def test_handle_paypal_signup_submitted_phase_returns_validation_error_and_releases_lock():
    calls = []

    result = payment_checkout_browser.handle_paypal_signup_submitted_phase(
        object(),
        signup_profile={},
        state={},
        card_retry_count=0,
        current_url="https://www.paypal.com/checkoutweb/signup",
        visible_validation_error=lambda _api: "please check your information",
        release_phone_lock=lambda _state, on_progress=None: calls.append("release"),
        retry_card_rejected=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not run")),
        stop_before_signup_otp_enabled=lambda: False,
        body_excerpt=lambda _api, limit=1600: "",
        has_otp_inputs=lambda _api: False,
        signup_otp_text_hint=lambda _text: False,
        stop_before_otp=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("stop should not run")),
        maybe_wait_for_otp=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
        submit_otp=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
    )

    assert result == (False, "PayPal 注册表单校验失败: please check your information", True)
    assert calls == ["release"]


def test_handle_paypal_signup_submitted_phase_routes_card_rejection_retry():
    api = object()
    state = {"card_rejected": True}
    progress_events = []
    on_progress = progress_events.append
    captured = {}

    result = payment_checkout_browser.handle_paypal_signup_submitted_phase(
        api,
        signup_profile={"phone": "8352880971"},
        state=state,
        card_retry_count=2,
        current_url="https://www.paypal.com/checkoutweb/signup",
        visible_validation_error=lambda _api: "",
        release_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("release should not run")),
        retry_card_rejected=lambda _api, **kwargs: captured.update({"api": _api, **kwargs}) or (True, "", True),
        stop_before_signup_otp_enabled=lambda: (_ for _ in ()).throw(AssertionError("stop flag should not run")),
        body_excerpt=lambda _api, limit=1600: "",
        has_otp_inputs=lambda _api: False,
        signup_otp_text_hint=lambda _text: False,
        stop_before_otp=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("stop should not run")),
        maybe_wait_for_otp=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
        submit_otp=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        on_progress=on_progress,
    )

    assert result == (True, "", True)
    assert captured["api"] is api
    assert captured["state"] is state
    assert captured["signup_profile"] == {"phone": "8352880971"}
    assert captured["card_retry_count"] == 2
    assert captured["current_url"] == "https://www.paypal.com/checkoutweb/signup"
    assert captured["on_progress"] is on_progress


def test_handle_paypal_signup_submitted_phase_stop_before_waits_for_otp_hint():
    calls = []
    sleeps = []

    result = payment_checkout_browser.handle_paypal_signup_submitted_phase(
        object(),
        signup_profile={"phone": "+817012345678"},
        state={},
        card_retry_count=0,
        current_url="https://www.paypal.com/checkoutweb/signup",
        visible_validation_error=lambda _api: "",
        release_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("release should not run")),
        retry_card_rejected=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not run")),
        stop_before_signup_otp_enabled=lambda: True,
        body_excerpt=lambda _api, limit=1600: calls.append("excerpt") or "still loading",
        has_otp_inputs=lambda _api: calls.append("inputs") or False,
        signup_otp_text_hint=lambda _text: calls.append("hint") or len(sleeps) >= 2,
        stop_before_otp=lambda **kwargs: calls.append(("stop", kwargs)) or (True, "", False),
        maybe_wait_for_otp=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
        submit_otp=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
        sleep=sleeps.append,
    )

    assert result == (True, "", False)
    assert sleeps == [0.5, 0.5]
    assert calls[:9] == ["excerpt", "inputs", "hint", "excerpt", "inputs", "hint", "excerpt", "inputs", "hint"]
    assert calls[-1][0] == "stop"


def test_handle_paypal_signup_submitted_phase_returns_otp_wait_result():
    result = payment_checkout_browser.handle_paypal_signup_submitted_phase(
        object(),
        signup_profile={},
        state={},
        card_retry_count=0,
        current_url="https://www.paypal.com/checkoutweb/signup",
        visible_validation_error=lambda _api: "",
        release_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("release should not run")),
        retry_card_rejected=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not run")),
        stop_before_signup_otp_enabled=lambda: False,
        body_excerpt=lambda _api, limit=1600: "",
        has_otp_inputs=lambda _api: False,
        signup_otp_text_hint=lambda _text: False,
        stop_before_otp=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("stop should not run")),
        maybe_wait_for_otp=lambda *_args, **_kwargs: (True, "", True),
        submit_otp=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("submit should not run")),
    )

    assert result == (True, "", True)


def test_handle_paypal_signup_submitted_phase_submits_otp_when_wait_continues_to_poll():
    api = object()
    state = {"needs_otp": True}
    def is_cancelled():
        return False
    captured = {}

    result = payment_checkout_browser.handle_paypal_signup_submitted_phase(
        api,
        signup_profile={"phone": "8352880971"},
        state=state,
        card_retry_count=0,
        current_url="https://www.paypal.com/checkoutweb/signup",
        is_cancelled=is_cancelled,
        visible_validation_error=lambda _api: "",
        release_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("release should not run")),
        retry_card_rejected=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry should not run")),
        stop_before_signup_otp_enabled=lambda: False,
        body_excerpt=lambda _api, limit=1600: "",
        has_otp_inputs=lambda _api: False,
        signup_otp_text_hint=lambda _text: False,
        stop_before_otp=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("stop should not run")),
        maybe_wait_for_otp=lambda *_args, **_kwargs: None,
        submit_otp=lambda _api, **kwargs: captured.update({"api": _api, **kwargs}) or (True, "", True),
    )

    assert result == (True, "", True)
    assert captured["api"] is api
    assert captured["signup_profile"] == {"phone": "8352880971"}
    assert captured["state"] is state
    assert captured["current_url"] == "https://www.paypal.com/checkoutweb/signup"
    assert captured["is_cancelled"] is is_cancelled


def test_maybe_wait_for_paypal_signup_otp_marks_ready_and_continues_to_poll():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    state = {"signup_submitted_at": 100.0}

    result = payment_checkout_browser.maybe_wait_for_paypal_signup_otp(
        api,
        state=state,
        signup_profile={"phone": "8352880971"},
        current_url="https://www.paypal.com/checkoutweb/signup",
        otp_wait_timeout_seconds=120,
        body_excerpt=lambda _api, limit: "Enter your code",
        has_otp_inputs=lambda _api: True,
        signup_otp_text_hint=lambda _text: False,
        click_create_submit=lambda _api: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        now=lambda: 101.0,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result is None
    assert state["otp_inputs_ready"] is True
    assert state["needs_otp"] is True


def test_maybe_wait_for_paypal_signup_otp_emits_wait_progress_when_not_ready():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    state = {"signup_submitted_at": 100.0}
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.maybe_wait_for_paypal_signup_otp(
        api,
        state=state,
        signup_profile={"otp_channel": "whatsapp", "phone": "+817012345678"},
        current_url="https://www.paypal.com/checkoutweb/signup",
        otp_wait_timeout_seconds=120,
        body_excerpt=lambda _api, limit: "still loading registration",
        has_otp_inputs=lambda _api: False,
        signup_otp_text_hint=lambda _text: False,
        click_create_submit=lambda _api: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        now=lambda: 101.0,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert state["_last_signup_otp_wait_excerpt"] == "still loading registration"
    assert progress_events == [
        {
            "stage": "paypal_wait_signup_otp",
            "url": "https://www.paypal.com/checkoutweb/signup",
            "otp_channel": "whatsapp",
            "phone": "+817012345678",
        }
    ]
    assert sleeps == [1.5]


def test_maybe_wait_for_paypal_signup_otp_times_out_waiting_for_inputs():
    result = payment_checkout_browser.maybe_wait_for_paypal_signup_otp(
        FakeApi(FakePage()),
        state={"signup_submitted_at": 100.0},
        signup_profile={},
        current_url="https://www.paypal.com/checkoutweb/signup",
        otp_wait_timeout_seconds=120,
        body_excerpt=lambda _api, limit: "still loading",
        has_otp_inputs=lambda _api: False,
        signup_otp_text_hint=lambda _text: False,
        click_create_submit=lambda _api: (_ for _ in ()).throw(AssertionError("submit should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        now=lambda: 221.0,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (False, "等待 PayPal 验证码超时", False)


def test_maybe_wait_for_paypal_signup_otp_clicks_agree_create_when_approve_ready():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    state = {"signup_submitted_at": 100.0, "approve_ready": True}
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.maybe_wait_for_paypal_signup_otp(
        api,
        state=state,
        signup_profile={},
        current_url="https://www.paypal.com/checkoutweb/signup",
        otp_wait_timeout_seconds=120,
        body_excerpt=lambda _api, limit: "agree and create account",
        has_otp_inputs=lambda _api: False,
        signup_otp_text_hint=lambda _text: False,
        click_create_submit=lambda _api: True,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        now=lambda: 101.0,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert progress_events == [
        {"stage": "paypal_agree_create_clicked", "url": "https://www.paypal.com/checkoutweb/signup"}
    ]
    assert api.page.loaded == [("domcontentloaded", 10000)]
    assert sleeps == [3.0]


def test_maybe_wait_for_paypal_signup_otp_falls_back_when_agree_create_missing():
    result = payment_checkout_browser.maybe_wait_for_paypal_signup_otp(
        FakeApi(FakePage()),
        state={"signup_submitted_at": 100.0, "approve_ready": True},
        signup_profile={},
        current_url="https://www.paypal.com/checkoutweb/signup",
        otp_wait_timeout_seconds=120,
        body_excerpt=lambda _api, limit: "agree and create account",
        has_otp_inputs=lambda _api: False,
        signup_otp_text_hint=lambda _text: False,
        click_create_submit=lambda _api: False,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        now=lambda: 101.0,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (True, "", False)


def test_submit_paypal_signup_otp_polls_fills_clicks_and_releases_lock():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    state = {}
    calls = []
    progress_events = []
    sleeps = []
    def is_cancelled():
        return False

    result = payment_checkout_browser.submit_paypal_signup_otp(
        api,
        signup_profile={"phone": "8352880971"},
        state=state,
        current_url="https://www.paypal.com/checkoutweb/signup",
        otp_poll_timeout_seconds=180,
        is_cancelled=is_cancelled,
        poll_signup_otp=lambda **kwargs: calls.append(("poll", kwargs)) or "123456",
        fill_otp_inputs=lambda _api, otp: calls.append(("fill", otp)) or True,
        click_next=lambda _api: calls.append("click_next") or True,
        release_phone_lock=lambda _state, on_progress=None: calls.append("release"),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        otp_cancelled_exception=RuntimeError,
        sleep=sleeps.append,
    )

    assert result == (True, "", True)
    assert calls[0][0] == "poll"
    assert calls[0][1]["signup_profile"] == {"phone": "8352880971"}
    assert calls[0][1]["timeout_seconds"] == 180
    assert calls[0][1]["is_cancelled"] is is_cancelled
    assert callable(calls[0][1]["on_progress"])
    assert calls[1:] == [("fill", "123456"), "click_next", "release"]
    assert progress_events == [{"stage": "paypal_submit_otp", "url": "https://www.paypal.com/checkoutweb/signup"}]
    assert sleeps == [2.0]


def test_submit_paypal_signup_otp_returns_timeout_message_on_cancelled_poll():
    result = payment_checkout_browser.submit_paypal_signup_otp(
        FakeApi(FakePage()),
        signup_profile={},
        state={},
        current_url="https://www.paypal.com/checkoutweb/signup",
        otp_poll_timeout_seconds=180,
        poll_signup_otp=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("no sms")),
        fill_otp_inputs=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fill should not run")),
        click_next=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("click should not run")),
        release_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("release should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        otp_cancelled_exception=RuntimeError,
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (False, "等待 PayPal OTP 超时: no sms", False)


def test_submit_paypal_signup_otp_returns_error_when_inputs_missing():
    result = payment_checkout_browser.submit_paypal_signup_otp(
        FakeApi(FakePage()),
        signup_profile={},
        state={},
        current_url="https://www.paypal.com/checkoutweb/signup",
        otp_poll_timeout_seconds=180,
        poll_signup_otp=lambda **_kwargs: "123456",
        fill_otp_inputs=lambda _api, _otp: False,
        click_next=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("click should not run")),
        release_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("release should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (False, "未找到 PayPal 验证码输入框", False)


def test_submit_paypal_signup_otp_returns_error_when_next_and_enter_fail():
    class BrokenKeyboard:
        def press(self, _key):
            raise RuntimeError("keyboard detached")

    page = FakePage(url="https://www.paypal.com/checkoutweb/signup")
    page.keyboard = BrokenKeyboard()

    result = payment_checkout_browser.submit_paypal_signup_otp(
        FakeApi(page),
        signup_profile={},
        state={},
        current_url="https://www.paypal.com/checkoutweb/signup",
        otp_poll_timeout_seconds=180,
        poll_signup_otp=lambda **_kwargs: "123456",
        fill_otp_inputs=lambda _api, _otp: True,
        click_next=lambda _api: False,
        release_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("release should not run")),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
    )

    assert result == (False, "未找到 PayPal 验证码提交按钮", False)


def test_paypal_signup_email_step_advanced_uses_url_and_state_signals():
    sync_calls = []
    before_url = "https://www.paypal.com/pay"
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))

    assert (
        payment_checkout_browser.paypal_signup_email_step_advanced(
            api,
            before_url,
            sync_payment_page=lambda api, **kwargs: sync_calls.append((api, kwargs)),
            is_pay_entry_url=lambda _url: False,
            inspect_page=lambda _api: (_ for _ in ()).throw(RuntimeError("should not inspect changed URL")),
        )
        is True
    )
    assert sync_calls == [(api, {"prefer_paypal": True})]

    api = FakeApi(FakePage(url=""))
    assert (
        payment_checkout_browser.paypal_signup_email_step_advanced(
            api,
            before_url,
            sync_payment_page=lambda *_args, **_kwargs: None,
            is_pay_entry_url=lambda url: url == before_url,
            inspect_page=lambda _api: (_ for _ in ()).throw(RuntimeError("should not inspect left /pay")),
        )
        is True
    )

    api = FakeApi(FakePage(url=before_url))
    assert (
        payment_checkout_browser.paypal_signup_email_step_advanced(
            api,
            before_url,
            sync_payment_page=lambda *_args, **_kwargs: None,
            is_pay_entry_url=lambda _url: False,
            inspect_page=lambda _api: {"registration_ready": False, "registration_text_hint": True},
        )
        is True
    )

    assert (
        payment_checkout_browser.paypal_signup_email_step_advanced(
            api,
            before_url,
            sync_payment_page=lambda *_args, **_kwargs: None,
            is_pay_entry_url=lambda _url: False,
            inspect_page=lambda _api: {
                "registration_ready": False,
                "registration_text_hint": False,
                "needs_otp": False,
            },
        )
        is False
    )


def test_wait_paypal_signup_email_step_advanced_waits_until_advanced():
    api = FakeApi(FakePage())
    checks = 0
    times = iter([0, 0.2, 0.6, 1.2])

    def step_advanced(_api, _before_url):
        nonlocal checks
        checks += 1
        return checks >= 3

    assert (
        payment_checkout_browser.wait_paypal_signup_email_step_advanced(
            api,
            "https://www.paypal.com/pay",
            step_advanced=step_advanced,
            timeout_seconds=1,
            now=lambda: next(times),
        )
        is True
    )
    assert checks == 3
    assert api.page.waited == [400, 400]


def test_wait_paypal_signup_email_step_advanced_uses_sleep_fallback_and_final_check():
    class RaisingWaitPage(FakePage):
        def wait_for_timeout(self, timeout):
            super().wait_for_timeout(timeout)
            raise RuntimeError("closed")

    api = FakeApi(RaisingWaitPage())
    sleeps = []
    checks = 0
    times = iter([0, 0.2, 1.2])

    def step_advanced(_api, _before_url):
        nonlocal checks
        checks += 1
        return checks == 2

    assert (
        payment_checkout_browser.wait_paypal_signup_email_step_advanced(
            api,
            "https://www.paypal.com/pay",
            step_advanced=step_advanced,
            timeout_seconds=1,
            now=lambda: next(times),
            sleep=sleeps.append,
        )
        is True
    )
    assert api.page.waited == [400]
    assert sleeps == [0.4]
    assert checks == 2


def test_js_click_paypal_signup_email_submit_uses_frames_and_logs_click():
    class FakeEvalFrame:
        def __init__(self, result):
            self.result = result
            self.evaluated = []

        def evaluate(self, script):
            self.evaluated.append(script)
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    failing_frame = FakeEvalFrame(RuntimeError("detached"))
    clicked_frame = FakeEvalFrame({"clicked": True, "text": "Continue"})
    logger = FakeLogger()

    assert (
        payment_checkout_browser.js_click_paypal_signup_email_submit(
            FakeApi(FakePage()),
            frames=lambda _api: [failing_frame, clicked_frame],
            logger=logger,
        )
        is True
    )
    assert "continue to payment" in clicked_frame.evaluated[0]
    assert logger.messages == [("[paypal_signup] JS email submit clicked: %s", ("Continue",))]


def test_js_click_paypal_signup_email_submit_accepts_true_and_false_results():
    class FakeEvalFrame:
        def __init__(self, result):
            self.result = result

        def evaluate(self, _script):
            return self.result

    assert (
        payment_checkout_browser.js_click_paypal_signup_email_submit(
            FakeApi(FakePage()),
            frames=lambda _api: [FakeEvalFrame(True)],
        )
        is True
    )
    assert (
        payment_checkout_browser.js_click_paypal_signup_email_submit(
            FakeApi(FakePage()),
            frames=lambda _api: [FakeEvalFrame({"clicked": False}), FakeEvalFrame(False)],
        )
        is False
    )


def test_js_recover_paypal_email_spinner_returns_dict_and_fallbacks():
    success_api = FakeApi(FakePage(evaluate_result={"recovered": True, "detail": "email_set;"}))

    assert payment_checkout_browser.js_recover_paypal_email_spinner(success_api, "demo@example.com") == {
        "recovered": True,
        "detail": "email_set;",
    }
    script, args = success_api.page.evaluated[0]
    assert "spinnerSelectors" in script
    assert args == ("demo@example.com",)

    assert payment_checkout_browser.js_recover_paypal_email_spinner(FakeApi(FakePage(evaluate_result=True)), "x") == {
        "recovered": False,
        "detail": "unexpected_return:True",
    }

    result = payment_checkout_browser.js_recover_paypal_email_spinner(
        FakeApi(FakePage(evaluate_result=RuntimeError("closed"))),
        "x",
    )
    assert result["recovered"] is False
    assert result["detail"].startswith("evaluate_error:closed")


def test_inspect_paypal_email_gate_returns_dict_and_error_fallbacks():
    gate = {"controls": [{"text": "Continue"}], "forms": [], "inputs": [], "title": "PayPal"}
    api = FakeApi(FakePage(evaluate_result=gate))

    assert payment_checkout_browser.inspect_paypal_email_gate(api) == gate
    assert "querySelectorAll('button" in api.page.evaluated[0][0]

    assert payment_checkout_browser.inspect_paypal_email_gate(FakeApi(FakePage(evaluate_result=True))) == {}
    assert payment_checkout_browser.inspect_paypal_email_gate(
        FakeApi(FakePage(evaluate_result=RuntimeError("detached")))
    ) == {"error": "detached"}


def test_submit_paypal_signup_email_step_validates_email_locator_and_fill():
    api = FakeApi(FakePage(url="https://www.paypal.com/pay"))

    base_kwargs = {
        "submit_selectors": ["submit"],
        "set_locator_value": lambda _locator, _email: True,
        "click_first": lambda _selectors, _timeout: True,
        "wait_step_advanced": lambda _api, _before_url, timeout_seconds=0: True,
        "js_click_submit": lambda _api: False,
        "inspect_gate": lambda _api: {},
        "body_excerpt": lambda _api, _limit: "",
        "progress_event": lambda stage, **extra: {"stage": stage, **extra},
    }

    assert payment_checkout_browser.submit_paypal_signup_email_step(
        api,
        signup_profile={},
        state={"email_locator": object()},
        **base_kwargs,
    ) == (False, "PayPal 注册邮箱为空")
    assert payment_checkout_browser.submit_paypal_signup_email_step(
        api,
        signup_profile={"email": "demo@example.com"},
        state={},
        **base_kwargs,
    ) == (False, "未找到 PayPal 注册邮箱输入框")
    assert payment_checkout_browser.submit_paypal_signup_email_step(
        api,
        signup_profile={"email": "demo@example.com"},
        state={"email_locator": object()},
        **{**base_kwargs, "set_locator_value": lambda _locator, _email: False},
    ) == (False, "填写 PayPal 注册邮箱失败")


def test_submit_paypal_signup_email_step_clicks_and_waits_for_advance():
    api = FakeApi(FakePage(url="https://www.paypal.com/pay"))
    events = []
    waits = []
    clicks = []
    locator = object()

    assert payment_checkout_browser.submit_paypal_signup_email_step(
        api,
        signup_profile={"email": " demo@example.com "},
        state={"email_locator": locator},
        submit_selectors=["submit"],
        set_locator_value=lambda value, email: value is locator and email == "demo@example.com",
        click_first=lambda selectors, timeout: clicks.append((selectors, timeout)) or True,
        wait_step_advanced=lambda _api, before_url, timeout_seconds=0: (
            waits.append((before_url, timeout_seconds)) or True
        ),
        js_click_submit=lambda _api: (_ for _ in ()).throw(RuntimeError("should not JS click")),
        inspect_gate=lambda _api: {},
        body_excerpt=lambda _api, _limit: "",
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=events.append,
    ) == (True, "")
    assert events == [{"stage": "paypal_signup_email", "url": "https://www.paypal.com/pay"}]
    assert clicks == [(["submit"], 2500)]
    assert waits == [("https://www.paypal.com/pay", 6.0)]


def test_submit_paypal_signup_email_step_treats_clicked_no_advance_as_submitted():
    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    api = FakeApi(FakePage(url="https://www.paypal.com/pay"))
    logger = FakeLogger()

    assert payment_checkout_browser.submit_paypal_signup_email_step(
        api,
        signup_profile={"email": "demo@example.com"},
        state={"email_locator": object()},
        submit_selectors=["submit"],
        set_locator_value=lambda _locator, _email: True,
        click_first=lambda _selectors, _timeout: True,
        wait_step_advanced=lambda _api, _before_url, timeout_seconds=0: False,
        js_click_submit=lambda _api: False,
        inspect_gate=lambda _api: {},
        body_excerpt=lambda _api, _limit: "",
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        logger=logger,
        url_summary=lambda url: f"summary:{url}",
    ) == (True, "")
    assert logger.messages == [
        (
            "[paypal_signup] email submit clicked but page did not advance (SPA may be stuck), "
            "treating as submitted to allow stuck-recovery: before=%s current=%s",
            ("summary:https://www.paypal.com/pay", "summary:https://www.paypal.com/pay"),
        )
    ]


def test_submit_paypal_signup_email_step_logs_gate_when_nothing_submitted():
    class FakeLocator:
        def __init__(self):
            self.presses = []

        def press(self, key, timeout=None):
            self.presses.append((key, timeout))
            raise RuntimeError("not focusable")

    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    locator = FakeLocator()
    logger = FakeLogger()
    api = FakeApi(FakePage(url="https://www.paypal.com/pay", body="Email gate body"))

    assert payment_checkout_browser.submit_paypal_signup_email_step(
        api,
        signup_profile={"email": "demo@example.com"},
        state={"email_locator": locator},
        submit_selectors=["submit"],
        set_locator_value=lambda _locator, _email: True,
        click_first=lambda _selectors, _timeout: False,
        wait_step_advanced=lambda _api, _before_url, timeout_seconds=0: False,
        js_click_submit=lambda _api: False,
        inspect_gate=lambda _api: {"controls": [{"text": "Continue"}]},
        body_excerpt=lambda api, limit: api.page.body[:limit],
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        logger=logger,
        url_summary=lambda url: f"summary:{url}",
        compact_log_text=lambda value, limit=0: f"compact:{value}",
    ) == (False, "PayPal 注册邮箱提交后未跳转到注册表单")
    assert locator.presses == [("Enter", 1200), ("Enter", 1200)]
    assert logger.messages == [
        (
            "[paypal_signup] email submit did not advance: before=%s current=%s gate=%s body=%s",
            (
                "summary:https://www.paypal.com/pay",
                "summary:https://www.paypal.com/pay",
                "compact:{'controls': [{'text': 'Continue'}]}",
                "compact:Email gate body",
            ),
        )
    ]


def test_click_paypal_phone_rejected_ok_in_frame_runs_dialog_script_safely():
    class FakeEvalFrame:
        def __init__(self, result):
            self.result = result
            self.evaluated = []

        def evaluate(self, script):
            self.evaluated.append(script)
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    frame = FakeEvalFrame(True)
    assert payment_checkout_browser.click_paypal_phone_rejected_ok_in_frame(frame) is True
    assert "try a different phone number" in frame.evaluated[0]
    assert (
        payment_checkout_browser.click_paypal_phone_rejected_ok_in_frame(FakeEvalFrame(RuntimeError("closed"))) is False
    )


def test_dismiss_paypal_phone_rejected_prompt_accepts_frame_ok_and_fallbacks():
    api = FakeApi(FakePage())
    sleeps = []
    has_prompt_calls = 0

    def has_prompt_after_frame(_api):
        nonlocal has_prompt_calls
        has_prompt_calls += 1
        return False

    assert (
        payment_checkout_browser.dismiss_paypal_phone_rejected_prompt(
            api,
            frames=lambda _api: ["frame"],
            click_ok_in_frame=lambda frame: frame == "frame",
            click_first=lambda _selectors, _timeout: False,
            has_prompt=has_prompt_after_frame,
            prompt_selectors=["dismiss"],
            sleep=sleeps.append,
        )
        is True
    )
    assert sleeps == [1.0]
    assert has_prompt_calls == 1

    api = FakeApi(FakePage())
    sleeps = []
    has_prompt_states = iter([True, False])

    assert (
        payment_checkout_browser.dismiss_paypal_phone_rejected_prompt(
            api,
            frames=lambda _api: [],
            click_ok_in_frame=lambda _frame: False,
            click_first=lambda selectors, timeout: selectors == ["dismiss"] and timeout == 1200,
            has_prompt=lambda _api: next(has_prompt_states),
            prompt_selectors=["dismiss"],
            sleep=sleeps.append,
        )
        is True
    )
    assert sleeps == [0.8, 0.5]
    assert api.page.keyboard.pressed == ["Escape"]


def test_has_paypal_phone_rejected_prompt_uses_selector_then_body_hint():
    api = FakeApi(FakePage(body="Try a different phone number"))

    assert (
        payment_checkout_browser.has_paypal_phone_rejected_prompt(
            api,
            rejected_selectors=["rejected"],
            visible_locator=lambda selectors, timeout: selectors == ["rejected"] and timeout == 500,
            body_excerpt=lambda _api, _limit: (_ for _ in ()).throw(RuntimeError("should not read body")),
            text_hint=lambda _text: False,
        )
        is True
    )

    assert (
        payment_checkout_browser.has_paypal_phone_rejected_prompt(
            api,
            rejected_selectors=["rejected"],
            visible_locator=lambda _selectors, _timeout: None,
            body_excerpt=lambda api, limit: api.page.body[:limit],
            text_hint=lambda text: "different phone" in text,
        )
        is True
    )

    assert (
        payment_checkout_browser.has_paypal_phone_rejected_prompt(
            api,
            rejected_selectors=["rejected"],
            visible_locator=lambda _selectors, _timeout: None,
            body_excerpt=lambda _api, _limit: (_ for _ in ()).throw(RuntimeError("closed")),
            text_hint=lambda text: bool(text),
        )
        is False
    )


def test_click_paypal_signup_otp_resend_clicks_frame_control_and_emits_progress():
    class FakeEvalFrame:
        def __init__(self, result):
            self.result = result
            self.evaluated = []

        def evaluate(self, script):
            self.evaluated.append(script)
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    failing_frame = FakeEvalFrame(RuntimeError("closed"))
    clicked_frame = FakeEvalFrame(True)
    progress_events = []
    sleeps = []

    assert (
        payment_checkout_browser.click_paypal_signup_otp_resend(
            api,
            frames=lambda _api: [failing_frame, clicked_frame],
            click_first=lambda _selectors, _timeout: (_ for _ in ()).throw(
                AssertionError("fallback should not run after frame click")
            ),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
            sleep=sleeps.append,
        )
        is True
    )
    assert "コードを再送信" in clicked_frame.evaluated[0]
    assert progress_events == [
        {
            "stage": "paypal_otp_resend_clicked",
            "url": "https://www.paypal.com/checkoutweb/signup",
        }
    ]
    assert sleeps == [1.0]


def test_click_paypal_signup_otp_resend_uses_japanese_fallback_selectors():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutweb/signup"))
    captured = {}
    progress_events = []

    result = payment_checkout_browser.click_paypal_signup_otp_resend(
        api,
        frames=lambda _api: [],
        click_first=lambda selectors, timeout: captured.update({"selectors": selectors, "timeout": timeout}) or True,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        sleep=lambda _seconds: None,
    )

    assert result is True
    assert captured["timeout"] == 1500
    assert any("コードを再送信" in selector for selector in captured["selectors"])
    assert any("もう一度送信" in selector for selector in captured["selectors"])
    assert progress_events == [
        {
            "stage": "paypal_otp_resend_clicked",
            "url": "https://www.paypal.com/checkoutweb/signup",
        }
    ]


def test_submit_paypal_login_step_fills_combined_form_and_clicks_next():
    class FakeLocator:
        def __init__(self, value=""):
            self.value = value
            self.pressed = []

        def input_value(self, timeout=None):
            return self.value

        def press(self, key, timeout=None):
            self.pressed.append((key, timeout))

    api = FakeApi(FakePage(url="https://www.paypal.com/signin"))
    email_locator = FakeLocator("old@example.com")
    password_locator = FakeLocator()
    writes = []
    clicks = []
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.submit_paypal_login_step(
        api,
        credentials={"email": "existing@example.com", "password": "Secret123!"},
        state={
            "login_phase": "login_combined",
            "email_locator": email_locator,
            "password_locator": password_locator,
        },
        next_selectors=["next"],
        set_locator_value=lambda locator, value: writes.append((locator, value)) or True,
        click_first=lambda selectors, timeout: clicks.append((selectors, timeout)) or True,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        sleep=sleeps.append,
    )

    assert result == (True, "")
    assert writes == [(email_locator, "existing@example.com"), (password_locator, "Secret123!")]
    assert clicks == [(["next"], 2500)]
    assert progress_events == [
        {"stage": "paypal_login_email", "url": "https://www.paypal.com/signin"},
        {"stage": "paypal_login_password", "url": "https://www.paypal.com/signin"},
    ]
    assert sleeps == [2.0]
    assert password_locator.pressed == []


def test_submit_paypal_login_step_reports_missing_password_and_submit_button():
    class FakeLocator:
        def __init__(self, *, fail_press=False):
            self.fail_press = fail_press

        def input_value(self, timeout=None):
            return "existing@example.com"

        def press(self, key, timeout=None):
            if self.fail_press:
                raise RuntimeError("closed")

    missing_password = payment_checkout_browser.submit_paypal_login_step(
        FakeApi(FakePage(url="https://www.paypal.com/signin")),
        credentials={"email": "existing@example.com"},
        state={"login_phase": "password", "password_locator": FakeLocator()},
        next_selectors=["next"],
        set_locator_value=lambda _locator, _value: True,
        click_first=lambda _selectors, _timeout: True,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run on failure")),
    )
    missing_submit = payment_checkout_browser.submit_paypal_login_step(
        FakeApi(FakePage(url="https://www.paypal.com/signin")),
        credentials={},
        state={},
        next_selectors=["next"],
        set_locator_value=lambda _locator, _value: True,
        click_first=lambda _selectors, _timeout: False,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run on failure")),
    )
    enter_failure = payment_checkout_browser.submit_paypal_login_step(
        FakeApi(FakePage(url="https://www.paypal.com/signin")),
        credentials={"email": "existing@example.com"},
        state={"login_phase": "email", "email_locator": FakeLocator(fail_press=True)},
        next_selectors=["next"],
        set_locator_value=lambda _locator, _value: True,
        click_first=lambda _selectors, _timeout: False,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run on failure")),
    )

    assert missing_password == (False, "自动 PayPal 模式缺少 paypal_password")
    assert missing_submit == (False, "未找到 PayPal 登录提交按钮")
    assert enter_failure == (False, "未找到 PayPal 登录提交按钮")


def test_click_paypal_approve_emits_progress_only_after_click():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutnow?token=demo"))
    calls = []
    progress_events = []

    assert (
        payment_checkout_browser.click_paypal_approve(
            api,
            approve_selectors=["approve"],
            click_first=lambda selectors, timeout: calls.append((selectors, timeout)) or True,
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
        )
        is True
    )
    assert calls == [(["approve"], 2500)]
    assert progress_events == [
        {
            "stage": "paypal_approve_clicked",
            "url": "https://www.paypal.com/checkoutnow?token=demo",
        }
    ]

    progress_events.clear()
    assert (
        payment_checkout_browser.click_paypal_approve(
            api,
            approve_selectors=["approve"],
            click_first=lambda _selectors, _timeout: False,
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            on_progress=progress_events.append,
        )
        is False
    )
    assert progress_events == []


def test_handle_paypal_left_host_skips_empty_or_paypal_url():
    for current_url in ["", "https://www.paypal.com/checkout"]:
        assert (
            payment_checkout_browser.handle_paypal_left_host(
                current_url=current_url,
                otp_phone_lock_key="otp-lock",
                paypal_host=lambda url: "paypal.com" in url,
                release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("release should not run")
                ),
                progress_event=lambda stage, **extra: {"stage": stage, **extra},
                on_progress=lambda _event: (_ for _ in ()).throw(AssertionError("progress should not run")),
            )
            is None
        )


def test_handle_paypal_left_host_releases_otp_lock_and_emits_wait_result():
    releases = []
    progress_events = []
    on_progress = progress_events.append

    result = payment_checkout_browser.handle_paypal_left_host(
        current_url="https://chatgpt.com/checkout/success",
        otp_phone_lock_key="otp-lock",
        paypal_host=lambda _url: False,
        release_otp_phone_lock=lambda key, **kwargs: releases.append((key, kwargs)),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=on_progress,
    )

    assert result == {"action": "return_none", "otp_phone_lock_key": ""}
    assert releases == [("otp-lock", {"on_progress": on_progress})]
    assert progress_events == [
        {
            "stage": "paypal_wait_result",
            "url": "https://chatgpt.com/checkout/success",
        }
    ]


def test_handle_paypal_left_host_emits_wait_result_without_lock():
    progress_events = []

    result = payment_checkout_browser.handle_paypal_left_host(
        current_url="https://chatgpt.com/checkout/success",
        otp_phone_lock_key="",
        paypal_host=lambda _url: False,
        release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release should not run")
        ),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
    )

    assert result == {"action": "return_none", "otp_phone_lock_key": ""}
    assert progress_events == [{"stage": "paypal_wait_result", "url": "https://chatgpt.com/checkout/success"}]


def test_paypal_left_host_values_returns_lock_key_default():
    assert payment_checkout_browser.paypal_left_host_values({}) == ""
    assert payment_checkout_browser.paypal_left_host_values({"otp_phone_lock_key": "otp-lock"}) == "otp-lock"


def test_prepare_paypal_authorize_flow_context_uses_active_signup_profile_credentials():
    signup_profile = {"email": "first@example.com", "password": "first-secret", "phone": "+12025550101"}
    pooled_profile = {"email": "pooled@example.com", "password": "pooled-secret", "phone": "+12025550102"}
    calls = []

    result = payment_checkout_browser.prepare_paypal_authorize_flow_context(
        paypal_mode="create_account",
        credentials={"email": "login@example.com", "password": "login-secret"},
        signup_profile=signup_profile,
        phone_accounts=[{"phone": "+12025550102"}],
        timeout_seconds=10,
        paypal_country=" jp ",
        paypal_lang="",
        normalize_paypal_country=lambda country: calls.append(("country", country)) or "JP",
        normalize_paypal_lang=lambda lang, country: calls.append(("lang", lang, country)) or "ja",
        signup_profiles_for_phone_pool=lambda profile, accounts: (
            calls.append(("profiles", profile, accounts)) or [pooled_profile]
        ),
        now=lambda: 100.0,
    )

    assert calls == [
        ("country", " jp "),
        ("lang", "", "JP"),
        ("profiles", signup_profile, [{"phone": "+12025550102"}]),
    ]
    assert result["deadline"] == 120.0
    assert result["paypal_country"] == "JP"
    assert result["paypal_lang"] == "ja"
    assert result["effective_credentials"] == {"email": "pooled@example.com", "password": "pooled-secret"}
    assert result["signup_profiles"] == [pooled_profile]
    assert result["signup_profile_index"] == 0
    assert result["active_signup_profile"] == pooled_profile
    assert result["submitted_phone_keys"] == set()
    assert result["max_ddc_blocked_refreshes"] == 3


def test_prepare_paypal_authorize_flow_context_keeps_login_credentials_and_profile_fallback():
    signup_profile = {"email": "signup@example.com", "password": "signup-secret"}
    credentials = {"email": "login@example.com", "password": "login-secret"}

    result = payment_checkout_browser.prepare_paypal_authorize_flow_context(
        paypal_mode="login",
        credentials=credentials,
        signup_profile=signup_profile,
        phone_accounts=None,
        timeout_seconds=60,
        paypal_country="US",
        paypal_lang="en",
        normalize_paypal_country=lambda country: country,
        normalize_paypal_lang=lambda lang, country: f"{lang}-{country}",
        signup_profiles_for_phone_pool=lambda _profile, _accounts: [],
        max_ddc_blocked_refreshes=5,
        now=lambda: 100.0,
    )

    assert result["deadline"] == 160.0
    assert result["paypal_lang"] == "en-US"
    assert result["effective_credentials"] == credentials
    assert result["effective_credentials"] is not credentials
    assert result["signup_profiles"] == []
    assert result["active_signup_profile"] == signup_profile
    assert result["state"] == {}
    assert result["max_ddc_blocked_refreshes"] == 5


def test_handle_paypal_authorize_cancelled_skips_when_not_cancelled():
    for is_cancelled in [lambda: False, None]:
        assert (
            payment_checkout_browser.handle_paypal_authorize_cancelled(
                is_cancelled=is_cancelled,
                otp_phone_lock_key="otp-lock",
                release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("release should not run")
                ),
            )
            is None
        )


def test_handle_paypal_authorize_cancelled_releases_lock_and_returns_failed_action():
    releases = []
    def on_progress(event):
        return None

    result = payment_checkout_browser.handle_paypal_authorize_cancelled(
        is_cancelled=lambda: True,
        otp_phone_lock_key="otp-lock",
        release_otp_phone_lock=lambda key, **kwargs: releases.append((key, kwargs)),
        on_progress=on_progress,
    )

    assert result == {
        "action": "failed",
        "otp_phone_lock_key": "",
        "screenshot_label": "paypal-cancelled",
        "failure_stage": "post_submit",
        "message": "任务已取消",
    }
    assert releases == [("otp-lock", {"on_progress": on_progress})]


def test_handle_paypal_authorize_cancelled_returns_failed_action_without_lock():
    result = payment_checkout_browser.handle_paypal_authorize_cancelled(
        is_cancelled=lambda: True,
        otp_phone_lock_key="",
        release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release should not run")
        ),
    )

    assert result == {
        "action": "failed",
        "otp_phone_lock_key": "",
        "screenshot_label": "paypal-cancelled",
        "failure_stage": "post_submit",
        "message": "任务已取消",
    }


def test_paypal_authorize_cancelled_result_fields_applies_defaults_and_overrides():
    assert payment_checkout_browser.paypal_authorize_cancelled_result_fields({}) == (
        "",
        "failed",
        "paypal-cancelled",
        "post_submit",
        "任务已取消",
    )
    assert payment_checkout_browser.paypal_authorize_cancelled_result_fields(
        {
            "otp_phone_lock_key": "otp-lock",
            "action": "needs_review",
            "screenshot_label": "custom-cancelled",
            "failure_stage": "custom_stage",
            "message": "custom message",
        }
    ) == ("otp-lock", "needs_review", "custom-cancelled", "custom_stage", "custom message")


def test_handle_paypal_phone_rejected_rotation_skips_when_not_eligible():
    assert (
        payment_checkout_browser.handle_paypal_phone_rejected_rotation(
            object(),
            paypal_mode="login",
            classified={"failure_stage": "paypal_phone_rejected"},
            signup_profile_index=0,
            signup_profiles=[{"phone": "111"}, {"phone": "222"}],
            active_signup_profile={"phone": "111"},
            current_url="https://www.paypal.com/checkout",
            otp_phone_lock_key="otp-lock",
            dismiss_phone_rejected_prompt=lambda _api: (_ for _ in ()).throw(AssertionError("dismiss should not run")),
            release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("release should not run")
            ),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            url_summary=lambda url: url,
        )
        is None
    )
    assert (
        payment_checkout_browser.handle_paypal_phone_rejected_rotation(
            object(),
            paypal_mode="create_account",
            classified={"failure_stage": "paypal_phone_rejected"},
            signup_profile_index=0,
            signup_profiles=[{"phone": "111"}],
            active_signup_profile={"phone": "111"},
            current_url="https://www.paypal.com/checkout",
            otp_phone_lock_key="otp-lock",
            dismiss_phone_rejected_prompt=lambda _api: (_ for _ in ()).throw(AssertionError("dismiss should not run")),
            release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("release should not run")
            ),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            url_summary=lambda url: url,
        )
        is None
    )


def test_handle_paypal_phone_rejected_rotation_continues_when_dismiss_fails():
    sleeps = []
    progress_events = []

    result = payment_checkout_browser.handle_paypal_phone_rejected_rotation(
        object(),
        paypal_mode="create_account",
        classified={"failure_stage": "paypal_phone_rejected"},
        signup_profile_index=0,
        signup_profiles=[{"phone": "111"}, {"phone": "222"}],
        active_signup_profile={"phone": "111"},
        current_url="https://www.paypal.com/checkout",
        otp_phone_lock_key="otp-lock",
        dismiss_phone_rejected_prompt=lambda _api: False,
        release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release should not run")
        ),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        url_summary=lambda url: f"summary:{url}",
        on_progress=progress_events.append,
        sleep=sleeps.append,
    )

    assert result == {"action": "continue"}
    assert sleeps == [1.0]
    assert progress_events == [
        {
            "stage": "paypal_phone_rejected_waiting_dismiss",
            "phone_pool_index": 1,
            "phone_pool_total": 2,
            "rejected_phone": "111",
            "url": "https://www.paypal.com/checkout",
            "level": "warn",
        }
    ]


def test_handle_paypal_phone_rejected_rotation_releases_lock_and_rotates_profile():
    releases = []
    sleeps = []
    progress_events = []
    on_progress = progress_events.append
    next_profile = {"phone": "222", "sms_url": "https://sms.example/two"}

    result = payment_checkout_browser.handle_paypal_phone_rejected_rotation(
        object(),
        paypal_mode="create_account",
        classified={"failure_stage": "paypal_phone_rejected"},
        signup_profile_index=0,
        signup_profiles=[{"phone": "111", "sms_url": "https://sms.example/one"}, next_profile],
        active_signup_profile={"phone": "111", "sms_url": "https://sms.example/one"},
        current_url="https://www.paypal.com/checkout",
        otp_phone_lock_key="otp-lock",
        dismiss_phone_rejected_prompt=lambda _api: True,
        release_otp_phone_lock=lambda key, **kwargs: releases.append((key, kwargs)),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        url_summary=lambda url: f"summary:{url}",
        on_progress=on_progress,
        sleep=sleeps.append,
    )

    assert result == {
        "action": "continue",
        "otp_phone_lock_key": "",
        "signup_profile_index": 1,
        "active_signup_profile": next_profile,
        "signup_form_submitted": False,
        "signup_submitted_at": 0.0,
        "phone_only_retry": True,
        "card_retry_count": 0,
    }
    assert releases == [("otp-lock", {"on_progress": on_progress})]
    assert sleeps == [1.5]
    assert progress_events == [
        {
            "stage": "paypal_phone_rejected_waiting_dismiss",
            "phone_pool_index": 1,
            "phone_pool_total": 2,
            "rejected_phone": "111",
            "url": "https://www.paypal.com/checkout",
            "level": "warn",
        },
        {
            "stage": "paypal_phone_rejected_rotate",
            "phone_pool_index": 2,
            "phone_pool_total": 2,
            "rejected_phone": "111",
            "next_phone": "222",
            "sms_url": "summary:https://sms.example/two",
            "url": "https://www.paypal.com/checkout",
            "level": "warn",
        },
    ]


def test_paypal_phone_rejected_rotation_values_preserves_defaults_and_coerces_overrides():
    active_profile = {"phone": "111"}
    next_profile = {"phone": "222"}

    assert payment_checkout_browser.paypal_phone_rejected_rotation_values(
        {},
        otp_phone_lock_key="otp-lock",
        signup_profile_index=1,
        active_signup_profile=active_profile,
        signup_form_submitted=True,
        signup_submitted_at=12.5,
        phone_only_retry=False,
        card_retry_count=3,
    ) == ("otp-lock", 1, active_profile, True, 12.5, False, 3)

    assert payment_checkout_browser.paypal_phone_rejected_rotation_values(
        {
            "otp_phone_lock_key": "",
            "signup_profile_index": "2",
            "active_signup_profile": next_profile,
            "signup_form_submitted": "",
            "signup_submitted_at": "0",
            "phone_only_retry": 1,
            "card_retry_count": "0",
        },
        otp_phone_lock_key="otp-lock",
        signup_profile_index=1,
        active_signup_profile=active_profile,
        signup_form_submitted=True,
        signup_submitted_at=12.5,
        phone_only_retry=False,
        card_retry_count=3,
    ) == ("", 2, next_profile, False, 0.0, True, 0)


def test_handle_paypal_authorize_failed_classification_skips_non_failed():
    assert (
        payment_checkout_browser.handle_paypal_authorize_failed_classification(
            object(),
            classified={"status": "needs_review", "failure_stage": "paypal_human_verification"},
            paypal_mode="create_account",
            active_signup_profile={"phone": "111"},
            signup_profile_index=0,
            signup_profiles=[{"phone": "111"}],
            current_url="https://www.paypal.com/checkout",
            otp_phone_lock_key="otp-lock",
            ddc_blocked_refresh_count=0,
            max_ddc_blocked_refreshes=3,
            release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("release should not run")
            ),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            logger=object(),
        )
        is None
    )


def test_handle_paypal_authorize_failed_classification_refreshes_datadome_blocked_page():
    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    class FakePage:
        def __init__(self):
            self.reloads = []

        def reload(self, **kwargs):
            self.reloads.append(kwargs)

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    api = FakeApi()
    logger = FakeLogger()
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.handle_paypal_authorize_failed_classification(
        api,
        classified={"status": "failed", "failure_stage": "paypal_datadome_blocked"},
        paypal_mode="create_account",
        active_signup_profile={"phone": "111"},
        signup_profile_index=0,
        signup_profiles=[{"phone": "111"}],
        current_url="https://www.paypal.com/checkout",
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=1,
        max_ddc_blocked_refreshes=3,
        release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release should not run")
        ),
        progress_event=lambda stage, *args, **extra: {"stage": stage, "args": args, **extra},
        logger=logger,
        on_progress=progress_events.append,
        sleep=sleeps.append,
    )

    assert result == {"action": "continue", "ddc_blocked_refresh_count": 2}
    assert api.page.reloads == [{"wait_until": "domcontentloaded", "timeout": 30000}]
    assert sleeps == [4]
    assert logger.messages == [
        (
            "[paypal_authorize] classify detected datadome_blocked, refreshing (%d/%d)...",
            (2, 3),
        )
    ]
    assert progress_events == [
        {
            "stage": "paypal_ddc_blocked_retry",
            "args": ("classify 检测到 DataDome 封锁，正在刷新重试 (2/3)",),
        }
    ]


def test_handle_paypal_authorize_failed_classification_releases_lock_and_returns_classified():
    releases = []
    progress_events = []
    classified = {
        "status": "failed",
        "failure_stage": "paypal_phone_rejected",
        "message": "PayPal 拒绝当前手机号，请更换手机号",
    }
    on_progress = progress_events.append

    result = payment_checkout_browser.handle_paypal_authorize_failed_classification(
        object(),
        classified=classified,
        paypal_mode="create_account",
        active_signup_profile={"phone": "111"},
        signup_profile_index=0,
        signup_profiles=[{"phone": "111"}],
        current_url="https://www.paypal.com/checkout",
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=3,
        max_ddc_blocked_refreshes=3,
        release_otp_phone_lock=lambda key, **kwargs: releases.append((key, kwargs)),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        logger=object(),
        on_progress=on_progress,
    )

    assert result == {
        "action": "return_classified",
        "classified": classified,
        "otp_phone_lock_key": "",
        "ddc_blocked_refresh_count": 3,
        "screenshot_label": "paypal-authorize-failed",
    }
    assert releases == [("otp-lock", {"on_progress": on_progress})]
    assert progress_events == [
        {
            "stage": "paypal_phone_rejected_final",
            "rejected_phone": "111",
            "phone_pool_index": 1,
            "phone_pool_total": 1,
            "url": "https://www.paypal.com/checkout",
            "level": "warn",
        }
    ]


def test_handle_paypal_authorize_review_classification_skips_non_human_review():
    assert (
        payment_checkout_browser.handle_paypal_authorize_review_classification(
            object(),
            classified={"status": "failed", "failure_stage": "paypal_human_verification"},
            otp_phone_lock_key="otp-lock",
            ddc_blocked_refresh_count=0,
            max_ddc_blocked_refreshes=3,
            is_ddc_blocked_page=lambda _page: (_ for _ in ()).throw(AssertionError("ddc should not run")),
            release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("release should not run")
            ),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            logger=object(),
        )
        is None
    )


def test_handle_paypal_authorize_review_classification_refreshes_datadome_blocked_page():
    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    class FakePage:
        def __init__(self):
            self.reloads = []

        def reload(self, **kwargs):
            self.reloads.append(kwargs)

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    api = FakeApi()
    logger = FakeLogger()
    progress_events = []
    sleeps = []

    result = payment_checkout_browser.handle_paypal_authorize_review_classification(
        api,
        classified={"status": "needs_review", "failure_stage": "paypal_human_verification"},
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=1,
        max_ddc_blocked_refreshes=3,
        is_ddc_blocked_page=lambda page: page is api.page,
        release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release should not run")
        ),
        progress_event=lambda stage, *args, **extra: {"stage": stage, "args": args, **extra},
        logger=logger,
        on_progress=progress_events.append,
        sleep=sleeps.append,
    )

    assert result == {"action": "continue", "ddc_blocked_refresh_count": 2}
    assert api.page.reloads == [{"wait_until": "domcontentloaded", "timeout": 30000}]
    assert sleeps == [4]
    assert logger.messages == [
        (
            "[paypal_authorize] human_verification is actually a blocked page, refreshing (%d/%d)...",
            (2, 3),
        )
    ]
    assert progress_events == [
        {
            "stage": "paypal_ddc_blocked_retry",
            "args": ("DataDome 封锁页面被误判为人机验证，正在刷新重试 (2/3)",),
        }
    ]


def test_handle_paypal_authorize_review_classification_releases_lock_and_returns_review():
    releases = []
    classified = {
        "status": "needs_review",
        "failure_stage": "paypal_human_verification",
        "message": "PayPal 需要人机验证",
    }
    def on_progress(event):
        return None

    result = payment_checkout_browser.handle_paypal_authorize_review_classification(
        object(),
        classified=classified,
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=3,
        max_ddc_blocked_refreshes=3,
        is_ddc_blocked_page=lambda _page: False,
        release_otp_phone_lock=lambda key, **kwargs: releases.append((key, kwargs)),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        logger=object(),
        on_progress=on_progress,
    )

    assert result == {
        "action": "return_classified",
        "classified": classified,
        "otp_phone_lock_key": "",
        "ddc_blocked_refresh_count": 3,
        "screenshot_label": "paypal-authorize-review",
    }
    assert releases == [("otp-lock", {"on_progress": on_progress})]


def test_paypal_authorize_classified_return_values_applies_fallbacks_and_overrides():
    fallback_classified = {
        "status": "failed",
        "failure_stage": "paypal_phone_rejected",
        "message": "fallback classified",
    }
    returned_classified = {
        "status": "needs_review",
        "failure_stage": "paypal_human_verification",
        "message": "returned classified",
    }

    assert payment_checkout_browser.paypal_authorize_classified_return_values(
        {},
        fallback_classified,
        default_screenshot_label="paypal-authorize-failed",
    ) == ("", "paypal-authorize-failed", fallback_classified)
    assert payment_checkout_browser.paypal_authorize_classified_return_values(
        {
            "otp_phone_lock_key": "otp-lock",
            "screenshot_label": "custom-review",
            "classified": returned_classified,
        },
        fallback_classified,
        default_screenshot_label="paypal-authorize-review",
    ) == ("otp-lock", "custom-review", returned_classified)
    assert payment_checkout_browser.paypal_authorize_classified_return_values(
        {},
        None,
        default_screenshot_label="paypal-authorize-review",
    ) == ("", "paypal-authorize-review", {})


def test_paypal_authorize_classification_refresh_count_preserves_default_and_coerces_override():
    assert (
        payment_checkout_browser.paypal_authorize_classification_refresh_count(
            {},
            ddc_blocked_refresh_count=2,
        )
        == 2
    )
    assert (
        payment_checkout_browser.paypal_authorize_classification_refresh_count(
            {"ddc_blocked_refresh_count": "3"},
            ddc_blocked_refresh_count=2,
        )
        == 3
    )


def test_paypal_authorize_datadome_failed_result_fields_applies_defaults_and_overrides():
    assert payment_checkout_browser.paypal_authorize_datadome_failed_result_fields(
        {},
        default_message="blocked",
    ) == ("", "paypal_datadome_blocked", "blocked")
    assert payment_checkout_browser.paypal_authorize_datadome_failed_result_fields(
        {
            "otp_phone_lock_key": "otp-lock",
            "failure_stage": "custom_stage",
            "message": "custom message",
        },
        default_stage="custom_default",
        default_message="blocked",
    ) == ("otp-lock", "custom_stage", "custom message")


def test_handle_paypal_authorize_ddc_blocked_page_skips_without_blocked_page():
    class FakeApi:
        page = object()

    assert (
        payment_checkout_browser.handle_paypal_authorize_ddc_blocked_page(
            FakeApi(),
            otp_phone_lock_key="otp-lock",
            ddc_blocked_refresh_count=0,
            max_ddc_blocked_refreshes=3,
            is_ddc_blocked_page=lambda _page: False,
            release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("release should not run")
            ),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            logger=object(),
            sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
        )
        is None
    )


def test_handle_paypal_authorize_ddc_blocked_page_reloads_and_returns_continue():
    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    class FakePage:
        def __init__(self):
            self.reloads = []

        def reload(self, **kwargs):
            self.reloads.append(kwargs)

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    api = FakeApi()
    logger = FakeLogger()
    sleeps = []
    progress_events = []

    result = payment_checkout_browser.handle_paypal_authorize_ddc_blocked_page(
        api,
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=1,
        max_ddc_blocked_refreshes=3,
        is_ddc_blocked_page=lambda page: page is api.page,
        release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release should not run")
        ),
        progress_event=lambda stage, *args, **extra: {"stage": stage, "args": args, **extra},
        logger=logger,
        on_progress=progress_events.append,
        sleep=sleeps.append,
    )

    assert result == {
        "action": "continue",
        "otp_phone_lock_key": "otp-lock",
        "ddc_blocked_refresh_count": 2,
    }
    assert api.page.reloads == [{"wait_until": "domcontentloaded", "timeout": 30000}]
    assert sleeps == [4]
    assert logger.messages == [
        (
            "[paypal_authorize] blocked page detected in main loop, refreshing (%d/%d)...",
            (2, 3),
        )
    ]
    assert progress_events == [
        {
            "stage": "paypal_ddc_blocked_retry",
            "args": ("检测到 DataDome 封锁页面，正在刷新重试 (2/3)",),
        }
    ]


def test_handle_paypal_authorize_ddc_blocked_page_releases_lock_and_returns_failed_after_limit():
    class FakeApi:
        page = object()

    releases = []
    def on_progress(event):
        return None

    result = payment_checkout_browser.handle_paypal_authorize_ddc_blocked_page(
        FakeApi(),
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=3,
        max_ddc_blocked_refreshes=3,
        is_ddc_blocked_page=lambda _page: True,
        release_otp_phone_lock=lambda key, **kwargs: releases.append((key, kwargs)),
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        logger=object(),
        on_progress=on_progress,
    )

    assert result == {
        "action": "failed",
        "otp_phone_lock_key": "",
        "ddc_blocked_refresh_count": 4,
        "failure_stage": "paypal_datadome_blocked",
        "message": "DataDome 封锁页面刷新 3 次仍未恢复",
    }
    assert releases == [("otp-lock", {"on_progress": on_progress})]


def test_paypal_authorize_ddc_blocked_page_values_preserves_defaults_and_coerces_overrides():
    assert payment_checkout_browser.paypal_authorize_ddc_blocked_page_values(
        {},
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=2,
    ) == ("otp-lock", 2)
    assert payment_checkout_browser.paypal_authorize_ddc_blocked_page_values(
        {
            "otp_phone_lock_key": "",
            "ddc_blocked_refresh_count": "3",
        },
        otp_phone_lock_key="otp-lock",
        ddc_blocked_refresh_count=2,
    ) == ("", 3)


def test_handle_paypal_authorize_ddc_challenge_skips_when_no_slider_and_iframe_check_not_due():
    class FakeApi:
        page = object()

    assert (
        payment_checkout_browser.handle_paypal_authorize_ddc_challenge(
            FakeApi(),
            otp_phone_lock_key="otp-lock",
            last_ddc_check_at=10.0,
            ddc_iframe_check_interval=15.0,
            ddc_pass_timeout_seconds=50,
            ddc_slider_visible=lambda _page: False,
            has_ddc_iframe=lambda _page: (_ for _ in ()).throw(AssertionError("iframe should not run")),
            wait_ddc_pass=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
            release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("release should not run")
            ),
            now=lambda: 20.0,
        )
        is None
    )


def test_handle_paypal_authorize_ddc_challenge_waits_for_iframe_and_returns_passed():
    class FakeApi:
        page = object()

    progress_events = []

    result = payment_checkout_browser.handle_paypal_authorize_ddc_challenge(
        FakeApi(),
        otp_phone_lock_key="otp-lock",
        last_ddc_check_at=10.0,
        ddc_iframe_check_interval=15.0,
        ddc_pass_timeout_seconds=50,
        ddc_slider_visible=lambda _page: False,
        has_ddc_iframe=lambda _page: True,
        wait_ddc_pass=lambda page, **kwargs: kwargs == {"timeout_seconds": 50, "on_progress": progress_events.append},
        release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release should not run")
        ),
        on_progress=progress_events.append,
        now=iter([30.0, 31.0]).__next__,
    )

    assert result == {
        "action": "passed",
        "otp_phone_lock_key": "otp-lock",
        "last_ddc_check_at": 31.0,
    }


def test_handle_paypal_authorize_ddc_challenge_releases_lock_and_returns_failed():
    class FakeApi:
        page = object()

    releases = []
    def on_progress(event):
        return None

    result = payment_checkout_browser.handle_paypal_authorize_ddc_challenge(
        FakeApi(),
        otp_phone_lock_key="otp-lock",
        last_ddc_check_at=10.0,
        ddc_iframe_check_interval=15.0,
        ddc_pass_timeout_seconds=50,
        ddc_slider_visible=lambda _page: True,
        has_ddc_iframe=lambda _page: (_ for _ in ()).throw(AssertionError("iframe should not run")),
        wait_ddc_pass=lambda _page, **kwargs: False,
        release_otp_phone_lock=lambda key, **kwargs: releases.append((key, kwargs)),
        on_progress=on_progress,
        now=lambda: 40.0,
    )

    assert result == {
        "action": "failed",
        "otp_phone_lock_key": "",
        "last_ddc_check_at": 40.0,
        "failure_stage": "paypal_datadome_blocked",
        "message": "DataDome 滑块/风控验证未通过",
    }
    assert releases == [("otp-lock", {"on_progress": on_progress})]


def test_paypal_authorize_ddc_challenge_values_preserves_defaults_and_coerces_overrides():
    assert payment_checkout_browser.paypal_authorize_ddc_challenge_values(
        {},
        otp_phone_lock_key="otp-lock",
        last_ddc_check_at=12.5,
    ) == ("otp-lock", 12.5)
    assert payment_checkout_browser.paypal_authorize_ddc_challenge_values(
        {
            "otp_phone_lock_key": "",
            "last_ddc_check_at": "0",
        },
        otp_phone_lock_key="otp-lock",
        last_ddc_check_at=12.5,
    ) == ("", 0.0)


def test_handle_paypal_result_datadome_check_skips_without_trigger():
    class FakeApi:
        page = object()

    assert (
        payment_checkout_browser.handle_paypal_result_datadome_check(
            FakeApi(),
            last_ddc_check_at=10.0,
            ddc_iframe_check_interval=15.0,
            ddc_pass_timeout_seconds=50,
            is_ddc_blocked_page=lambda _page: False,
            ddc_slider_visible=lambda _page: False,
            has_ddc_iframe=lambda _page: False,
            wait_ddc_pass=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
            logger=object(),
            now=lambda: 30.0,
        )
        is None
    )


def test_handle_paypal_result_datadome_check_refreshes_blocked_page_and_continues():
    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    class FakePage:
        def __init__(self):
            self.reloads = []

        def reload(self, **kwargs):
            self.reloads.append(kwargs)

    class FakeApi:
        def __init__(self):
            self.page = FakePage()

    api = FakeApi()
    logger = FakeLogger()
    sleeps = []

    result = payment_checkout_browser.handle_paypal_result_datadome_check(
        api,
        last_ddc_check_at=10.0,
        ddc_iframe_check_interval=15.0,
        ddc_pass_timeout_seconds=50,
        is_ddc_blocked_page=lambda page: page is api.page,
        ddc_slider_visible=lambda _page: (_ for _ in ()).throw(AssertionError("slider should not run")),
        has_ddc_iframe=lambda _page: (_ for _ in ()).throw(AssertionError("iframe should not run")),
        wait_ddc_pass=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
        logger=logger,
        sleep=sleeps.append,
    )

    assert result == {"action": "continue", "last_ddc_check_at": 10.0}
    assert api.page.reloads == [{"wait_until": "domcontentloaded", "timeout": 30000}]
    assert sleeps == [4]
    assert logger.messages == [("[paypal_result] blocked page detected, refreshing...", ())]


def test_handle_paypal_result_datadome_check_waits_for_challenge_and_returns_checked():
    class FakeApi:
        page = object()

    progress_events = []
    waits = []

    result = payment_checkout_browser.handle_paypal_result_datadome_check(
        FakeApi(),
        last_ddc_check_at=10.0,
        ddc_iframe_check_interval=15.0,
        ddc_pass_timeout_seconds=50,
        is_ddc_blocked_page=lambda _page: False,
        ddc_slider_visible=lambda _page: True,
        has_ddc_iframe=lambda _page: (_ for _ in ()).throw(AssertionError("iframe should not run")),
        wait_ddc_pass=lambda page, **kwargs: waits.append((page, kwargs)) or False,
        logger=object(),
        on_progress=progress_events.append,
        now=lambda: 40.0,
    )

    assert result == {"action": "checked", "last_ddc_check_at": 40.0}
    assert waits == [
        (
            FakeApi.page,
            {"timeout_seconds": 50, "on_progress": progress_events.append},
        )
    ]


def test_paypal_result_datadome_values_preserves_default_and_coerces_override():
    assert payment_checkout_browser.paypal_result_datadome_values({}, last_ddc_check_at=12.5) == 12.5
    assert (
        payment_checkout_browser.paypal_result_datadome_values(
            {"last_ddc_check_at": "0"},
            last_ddc_check_at=12.5,
        )
        == 0.0
    )


def test_should_continue_after_paypal_result_datadome_only_for_continue_action():
    assert payment_checkout_browser.should_continue_after_paypal_result_datadome({"action": "continue"})
    assert not payment_checkout_browser.should_continue_after_paypal_result_datadome({"action": "checked"})
    assert not payment_checkout_browser.should_continue_after_paypal_result_datadome({})


def test_paypal_result_datadome_transition_returns_timestamp_and_continue_decision():
    assert payment_checkout_browser.paypal_result_datadome_transition(
        {"action": "continue", "last_ddc_check_at": "0"},
        last_ddc_check_at=12.5,
    ) == (0.0, True)
    assert payment_checkout_browser.paypal_result_datadome_transition(
        {"action": "checked"},
        last_ddc_check_at=12.5,
    ) == (12.5, False)


def test_should_check_paypal_result_datadome_delegates_to_paypal_host_check():
    captured = {}

    def fake_is_paypal_host(current_url):
        captured["current_url"] = current_url
        return True

    assert payment_checkout_browser.should_check_paypal_result_datadome(
        "https://www.paypal.com/checkoutnow",
        is_paypal_host=fake_is_paypal_host,
    )
    assert captured["current_url"] == "https://www.paypal.com/checkoutnow"


def test_paypal_result_browser_classification_delegates_to_classifier():
    captured = {}
    classified = {"status": "success"}

    def fake_classify(current_url, body_text):
        captured["current_url"] = current_url
        captured["body_text"] = body_text
        return classified

    assert (
        payment_checkout_browser.paypal_result_browser_classification(
            "https://www.paypal.com/checkoutnow",
            "body",
            classify_checkout_state=fake_classify,
        )
        is classified
    )
    assert captured == {
        "current_url": "https://www.paypal.com/checkoutnow",
        "body_text": "body",
    }


def test_paypal_result_browser_classified_values_returns_none_without_classification():
    assert (
        payment_checkout_browser.paypal_result_browser_classified_values(
            "https://www.paypal.com/checkoutnow",
            "body",
            classify_checkout_state=lambda _url, _body: None,
        )
        is None
    )


def test_paypal_result_browser_classified_values_returns_status_and_result_by_reference():
    classified = {"status": "success"}

    assert payment_checkout_browser.paypal_result_browser_classified_values(
        "https://www.paypal.com/checkoutnow",
        "body",
        classify_checkout_state=lambda _url, _body: classified,
    ) == ("success", classified)


def test_paypal_result_classified_return_values_returns_status_and_result_by_reference():
    classified = {"status": "failed", "failure_stage": "paypal_failed"}

    assert payment_checkout_browser.paypal_result_classified_return_values(classified) == ("failed", classified)


def test_attach_paypal_result_screenshot_paths_mutates_and_returns_result_by_reference():
    classified = {"status": "failed"}
    screenshot_paths = ["paypal-failed.png"]

    result = payment_checkout_browser.attach_paypal_result_screenshot_paths(classified, screenshot_paths)

    assert result is classified
    assert classified["screenshot_paths"] is screenshot_paths


def test_paypal_result_cancelled_result_fields_preserves_defaults_and_coerces_overrides():
    assert payment_checkout_browser.paypal_result_cancelled_result_fields() == (
        "failed",
        "paypal-cancelled",
        "post_submit",
        "任务已取消",
    )
    assert payment_checkout_browser.paypal_result_cancelled_result_fields(
        {
            "action": "needs_review",
            "screenshot_label": "custom-cancelled",
            "failure_stage": "custom_stage",
            "message": 123,
        }
    ) == ("needs_review", "custom-cancelled", "custom_stage", "123")


def test_paypal_result_timeout_result_fields_preserves_defaults_and_coerces_overrides():
    assert payment_checkout_browser.paypal_result_timeout_result_fields() == (
        "needs_review",
        "paypal-timeout",
        "post_submit",
        "等待 PayPal 支付结果超时，需要人工确认最终状态",
    )
    assert payment_checkout_browser.paypal_result_timeout_result_fields(
        {
            "action": "failed",
            "screenshot_label": "custom-timeout",
            "failure_stage": "custom_timeout",
            "message": 456,
        }
    ) == ("failed", "custom-timeout", "custom_timeout", "456")


def test_paypal_result_wait_deadline_applies_minimum_timeout():
    assert payment_checkout_browser.paypal_result_wait_deadline(now=100.0, timeout_seconds=0) == 110.0
    assert payment_checkout_browser.paypal_result_wait_deadline(now=100.0, timeout_seconds=5) == 110.0
    assert payment_checkout_browser.paypal_result_wait_deadline(now=100.0, timeout_seconds=30) == 130.0


def test_should_continue_paypal_result_wait_stops_at_deadline():
    assert payment_checkout_browser.should_continue_paypal_result_wait(now=109.99, deadline=110.0)
    assert not payment_checkout_browser.should_continue_paypal_result_wait(now=110.0, deadline=110.0)
    assert not payment_checkout_browser.should_continue_paypal_result_wait(now=111.0, deadline=110.0)


def test_should_cancel_paypal_result_wait_calls_cancel_callback_only_when_callable():
    calls = []

    assert not payment_checkout_browser.should_cancel_paypal_result_wait(None)
    assert not payment_checkout_browser.should_cancel_paypal_result_wait(False)
    assert payment_checkout_browser.should_cancel_paypal_result_wait(lambda: calls.append("called") or True)
    assert calls == ["called"]


def test_paypal_result_wait_initial_state_returns_default_loop_values():
    assert payment_checkout_browser.paypal_result_wait_initial_state() == ("", 0.0, 0.0, 0.0)


def test_paypal_result_wait_sleep_seconds_returns_poll_interval():
    assert payment_checkout_browser.paypal_result_wait_sleep_seconds() == 3.0


def test_paypal_result_autofilled_url_keys_returns_new_empty_set():
    first = payment_checkout_browser.paypal_result_autofilled_url_keys()
    second = payment_checkout_browser.paypal_result_autofilled_url_keys()

    assert first == set()
    assert second == set()
    assert first is not second


def test_paypal_result_stripe_state_http_session_uses_non_curl_http_session():
    captured = {}
    http_session = object()

    def fake_new_http_session(proxy_url, **kwargs):
        captured["proxy_url"] = proxy_url
        captured.update(kwargs)
        return http_session

    assert (
        payment_checkout_browser.paypal_result_stripe_state_http_session(
            "http://proxy.example:8080",
            new_http_session=fake_new_http_session,
        )
        is http_session
    )
    assert captured == {
        "proxy_url": "http://proxy.example:8080",
        "require_curl_cffi": False,
    }


def test_paypal_result_page_snapshot_reads_body_and_current_url():
    captured = {}
    api = type("Api", (), {"page": type("Page", (), {"url": "https://www.paypal.com/checkoutnow"})()})()

    def fake_body_excerpt(received_api):
        captured["api"] = received_api
        return "PayPal body"

    assert payment_checkout_browser.paypal_result_page_snapshot(api, body_excerpt=fake_body_excerpt) == (
        "PayPal body",
        "https://www.paypal.com/checkoutnow",
    )
    assert captured["api"] is api


def test_paypal_result_sync_prefer_paypal_returns_result_wait_preference():
    assert payment_checkout_browser.paypal_result_sync_prefer_paypal() is True


def test_paypal_result_autofill_url_key_ignores_query_and_fragment():
    assert (
        payment_checkout_browser.paypal_result_autofill_url_key(
            "https://checkout.openai.com/pay/cs_123?prefilled=1#section"
        )
        == "https://checkout.openai.com/pay/cs_123"
    )
    assert payment_checkout_browser.paypal_result_autofill_url_key("") == ""


def test_should_autofill_paypal_result_checkout_short_circuits_without_payload():
    assert not payment_checkout_browser.should_autofill_paypal_result_checkout(
        "https://checkout.openai.com/pay/cs_123",
        None,
        is_checkout_host=lambda _url: (_ for _ in ()).throw(AssertionError("host check should not run")),
        autofill_allowed=lambda _url: (_ for _ in ()).throw(AssertionError("allowed check should not run")),
    )


def test_should_autofill_paypal_result_checkout_short_circuits_when_disabled():
    assert not payment_checkout_browser.should_autofill_paypal_result_checkout(
        "https://checkout.openai.com/pay/cs_123",
        {"name": "James Smith"},
        autofill_enabled=False,
        is_checkout_host=lambda _url: (_ for _ in ()).throw(AssertionError("host check should not run")),
        autofill_allowed=lambda _url: (_ for _ in ()).throw(AssertionError("allowed check should not run")),
    )


def test_should_autofill_paypal_result_checkout_short_circuits_when_not_checkout_host():
    assert not payment_checkout_browser.should_autofill_paypal_result_checkout(
        "https://example.com/",
        {"name": "James Smith"},
        is_checkout_host=lambda _url: False,
        autofill_allowed=lambda _url: (_ for _ in ()).throw(AssertionError("allowed check should not run")),
    )


def test_should_autofill_paypal_result_checkout_requires_allowed_checkout_url():
    assert not payment_checkout_browser.should_autofill_paypal_result_checkout(
        "https://checkout.openai.com/pay/cs_123",
        {"name": "James Smith"},
        is_checkout_host=lambda _url: True,
        autofill_allowed=lambda _url: False,
    )
    assert payment_checkout_browser.should_autofill_paypal_result_checkout(
        "https://checkout.openai.com/pay/cs_123",
        {"name": "James Smith"},
        is_checkout_host=lambda _url: True,
        autofill_allowed=lambda _url: True,
    )


def test_should_run_paypal_result_autofill_requires_trigger_and_unseen_key():
    assert not payment_checkout_browser.should_run_paypal_result_autofill(
        should_autofill_checkout=False,
        autofill_key="checkout-key",
        autofilled_url_keys=set(),
    )
    assert not payment_checkout_browser.should_run_paypal_result_autofill(
        should_autofill_checkout=True,
        autofill_key="checkout-key",
        autofilled_url_keys={"checkout-key"},
    )
    assert payment_checkout_browser.should_run_paypal_result_autofill(
        should_autofill_checkout=True,
        autofill_key="checkout-key",
        autofilled_url_keys=set(),
    )


def test_paypal_result_autofill_transition_returns_run_decision_and_url_key():
    assert payment_checkout_browser.paypal_result_autofill_transition(
        "https://checkout.openai.com/pay/cs_123?prefilled=1#section",
        {"name": "James Smith"},
        autofilled_url_keys=set(),
        autofill_enabled=False,
        is_checkout_host=lambda _url: True,
        autofill_allowed=lambda _url: True,
    ) == (False, "https://checkout.openai.com/pay/cs_123")
    assert payment_checkout_browser.paypal_result_autofill_transition(
        "https://checkout.openai.com/pay/cs_123?prefilled=1#section",
        {"name": "James Smith"},
        autofilled_url_keys=set(),
        is_checkout_host=lambda _url: True,
        autofill_allowed=lambda _url: True,
    ) == (True, "https://checkout.openai.com/pay/cs_123")
    assert payment_checkout_browser.paypal_result_autofill_transition(
        "https://checkout.openai.com/pay/cs_123?prefilled=1#section",
        {"name": "James Smith"},
        autofilled_url_keys={"https://checkout.openai.com/pay/cs_123"},
        is_checkout_host=lambda _url: True,
        autofill_allowed=lambda _url: True,
    ) == (False, "https://checkout.openai.com/pay/cs_123")


def test_record_paypal_result_autofill_key_mutates_and_returns_set_by_reference():
    autofilled_url_keys = {"existing-key"}

    result = payment_checkout_browser.record_paypal_result_autofill_key(
        autofilled_url_keys,
        "checkout-key",
    )

    assert result is autofilled_url_keys
    assert autofilled_url_keys == {"existing-key", "checkout-key"}


def test_paypal_result_stripe_progress_event_fields_uses_message_and_urls():
    assert payment_checkout_browser.paypal_result_stripe_progress_event_fields(
        {"message": "confirmed"},
        checkout_url="https://checkout.openai.com/pay/cs_123",
        current_url="https://www.paypal.com/checkoutnow",
    ) == (
        "paypal_result_confirmed_by_stripe",
        "confirmed",
        {
            "checkout_url": "https://checkout.openai.com/pay/cs_123",
            "url": "https://www.paypal.com/checkoutnow",
        },
    )


def test_paypal_result_stripe_progress_event_fields_uses_default_message():
    assert payment_checkout_browser.paypal_result_stripe_progress_event_fields(
        {},
        checkout_url="checkout",
        current_url="current",
    ) == (
        "paypal_result_confirmed_by_stripe",
        "Stripe checkout 状态已确认",
        {"checkout_url": "checkout", "url": "current"},
    )


def test_paypal_result_stripe_classified_values_combines_progress_and_return_values():
    stripe_classified = {"status": "success", "message": "confirmed"}

    assert payment_checkout_browser.paypal_result_stripe_classified_values(
        stripe_classified,
        checkout_url="checkout",
        current_url="current",
    ) == (
        "paypal_result_confirmed_by_stripe",
        "confirmed",
        {"checkout_url": "checkout", "url": "current"},
        "success",
        stripe_classified,
    )


def test_should_poll_paypal_result_stripe_state_requires_checkout_url():
    assert not payment_checkout_browser.should_poll_paypal_result_stripe_state(
        checkout_url="",
        now=10.0,
        last_poll_at=0.0,
        poll_interval_seconds=5.0,
    )


def test_should_poll_paypal_result_stripe_state_respects_interval_boundary():
    assert not payment_checkout_browser.should_poll_paypal_result_stripe_state(
        checkout_url="checkout",
        now=4.99,
        last_poll_at=0.0,
        poll_interval_seconds=5.0,
    )
    assert payment_checkout_browser.should_poll_paypal_result_stripe_state(
        checkout_url="checkout",
        now=5.0,
        last_poll_at=0.0,
        poll_interval_seconds=5.0,
    )


def test_paypal_result_stripe_poll_transition_updates_timestamp_only_when_polling():
    assert payment_checkout_browser.paypal_result_stripe_poll_transition(
        checkout_url="",
        now=10.0,
        last_poll_at=4.0,
        poll_interval_seconds=5.0,
    ) == (False, 4.0)
    assert payment_checkout_browser.paypal_result_stripe_poll_transition(
        checkout_url="checkout",
        now=10.0,
        last_poll_at=4.0,
        poll_interval_seconds=5.0,
    ) == (True, 10.0)


def test_should_emit_paypal_result_stage_progress_only_on_stage_change():
    assert not payment_checkout_browser.should_emit_paypal_result_stage_progress(
        stage="paypal_pending",
        last_stage="paypal_pending",
    )
    assert payment_checkout_browser.should_emit_paypal_result_stage_progress(
        stage="paypal_pending",
        last_stage="",
    )


def test_paypal_result_stage_values_delegates_to_stage_inferer():
    captured = {}

    def fake_infer_stage(current_url, body_text):
        captured["current_url"] = current_url
        captured["body_text"] = body_text
        return "paypal_pending", "等待 PayPal"

    assert payment_checkout_browser.paypal_result_stage_values(
        "https://www.paypal.com/checkoutnow",
        "body",
        infer_stage=fake_infer_stage,
    ) == ("paypal_pending", "等待 PayPal")
    assert captured == {
        "current_url": "https://www.paypal.com/checkoutnow",
        "body_text": "body",
    }


def test_paypal_result_stage_progress_transition_updates_last_stage_only_on_change():
    assert payment_checkout_browser.paypal_result_stage_progress_transition(
        stage="paypal_pending",
        last_stage="paypal_pending",
    ) == (False, "paypal_pending")
    assert payment_checkout_browser.paypal_result_stage_progress_transition(
        stage="paypal_complete",
        last_stage="paypal_pending",
    ) == (True, "paypal_complete")


def test_paypal_result_stage_progress_event_fields_returns_stage_message_and_url():
    assert payment_checkout_browser.paypal_result_stage_progress_event_fields(
        stage="paypal_pending",
        message="等待 PayPal",
        current_url="https://www.paypal.com/checkoutnow",
    ) == (
        "paypal_pending",
        "等待 PayPal",
        {"url": "https://www.paypal.com/checkoutnow"},
    )


def test_should_log_paypal_result_wait_respects_interval_boundary():
    assert not payment_checkout_browser.should_log_paypal_result_wait(
        now=59.99,
        last_log_at=0.0,
        log_interval_seconds=60.0,
    )
    assert payment_checkout_browser.should_log_paypal_result_wait(
        now=60.0,
        last_log_at=0.0,
        log_interval_seconds=60.0,
    )


def test_paypal_result_wait_log_transition_updates_timestamp_only_when_logging():
    assert payment_checkout_browser.paypal_result_wait_log_transition(
        now=59.99,
        last_log_at=0.0,
        log_interval_seconds=60.0,
    ) == (False, 0.0)
    assert payment_checkout_browser.paypal_result_wait_log_transition(
        now=60.0,
        last_log_at=0.0,
        log_interval_seconds=60.0,
    ) == (True, 60.0)


def test_paypal_result_wait_log_values_clamps_remaining_and_preserves_url():
    assert payment_checkout_browser.paypal_result_wait_log_values(
        deadline=120.9,
        now=60.1,
        current_url="https://www.paypal.com/checkoutnow",
    ) == (60, "https://www.paypal.com/checkoutnow")
    assert payment_checkout_browser.paypal_result_wait_log_values(
        deadline=10.0,
        now=12.0,
        current_url="",
    ) == (0, "")


def test_handle_paypal_browser_fallback_ddc_wait_returns_continue_when_passed():
    page = object()
    progress_events = []
    waits = []

    assert payment_checkout_browser.handle_paypal_browser_fallback_ddc_wait(
        page,
        wait_ddc_pass=lambda passed_page, **kwargs: waits.append((passed_page, kwargs)) or True,
        timeout_seconds=50,
        on_progress=progress_events.append,
    ) == {"action": "continue"}
    assert waits == [
        (
            page,
            {"timeout_seconds": 50, "on_progress": progress_events.append},
        )
    ]


def test_handle_paypal_browser_fallback_ddc_wait_returns_failed_metadata_when_blocked():
    assert payment_checkout_browser.handle_paypal_browser_fallback_ddc_wait(
        object(),
        wait_ddc_pass=lambda *_args, **_kwargs: False,
        timeout_seconds=50,
    ) == {
        "action": "failed",
        "failure_stage": "paypal_datadome_blocked",
        "message": "浏览器降级后 DataDome 滑块/风控仍未通过",
    }


def test_handle_paypal_protocol_browser_fallback_context_returns_protocol_result_without_approve_url():
    protocol_result = {"status": "needs_review"}
    progress_events = []

    result = payment_checkout_browser.handle_paypal_protocol_browser_fallback_context(
        protocol_result,
        paypal_mode="login",
        paypal_country="US",
        paypal_lang="en",
        extract_ba_token=lambda url: "",
        create_account_entry_url=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("entry url should not run")
        ),
        safe_url_summary=lambda url: f"summary:{url}",
        progress_event=lambda stage, *args, **extra: {"stage": stage, "args": args, **extra},
        on_progress=progress_events.append,
    )

    assert result == {
        "action": "return_protocol_result",
        "protocol_result": protocol_result,
        "paypal_approve_url": "",
        "ba_token": "",
    }
    assert progress_events == [
        {
            "stage": "paypal_protocol_browser_fallback",
            "args": ("协议模式被 PayPal 风控拦截，正在降级到浏览器模式",),
            "paypal_approve_url": "summary:",
            "ba_token": "",
        }
    ]


def test_handle_paypal_protocol_browser_fallback_context_returns_login_entry_url():
    progress_events = []

    result = payment_checkout_browser.handle_paypal_protocol_browser_fallback_context(
        {
            "paypal_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
            "ba_token": "BA-EXPLICIT",
        },
        paypal_mode="login",
        paypal_country="JP",
        paypal_lang="ja",
        extract_ba_token=lambda _url: (_ for _ in ()).throw(AssertionError("extract should not run")),
        create_account_entry_url=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("entry url should not run")
        ),
        safe_url_summary=lambda url: f"summary:{url}",
        progress_event=lambda stage, *args, **extra: {"stage": stage, "args": args, **extra},
        on_progress=progress_events.append,
    )

    assert result == {
        "action": "fallback",
        "paypal_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
        "ba_token": "BA-EXPLICIT",
        "browser_entry_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
    }
    assert progress_events[0]["paypal_approve_url"] == (
        "summary:https://www.paypal.com/agreements/approve?ba_token=BA-DEMO"
    )
    assert progress_events[0]["ba_token"] == "BA-EXPLICIT"


def test_handle_paypal_protocol_browser_fallback_context_returns_create_account_entry_url():
    created = {}

    def fake_create_account_entry_url(url, **kwargs):
        created["call"] = (url, kwargs)
        return "https://www.paypal.com/checkoutweb/signup?ba_token=BA-EXTRACTED"

    result = payment_checkout_browser.handle_paypal_protocol_browser_fallback_context(
        {"paypal_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO"},
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        extract_ba_token=lambda url: "BA-EXTRACTED" if "ba_token=BA-DEMO" in url else "",
        create_account_entry_url=fake_create_account_entry_url,
        safe_url_summary=lambda url: url,
        progress_event=lambda stage, *args, **extra: {"stage": stage, "args": args, **extra},
    )

    assert result == {
        "action": "fallback",
        "paypal_approve_url": "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
        "ba_token": "BA-EXTRACTED",
        "browser_entry_url": "https://www.paypal.com/checkoutweb/signup?ba_token=BA-EXTRACTED",
    }
    assert created["call"] == (
        "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
        {"ba_token": "BA-EXTRACTED", "country": "JP", "lang": "ja"},
    )


def test_preserve_paypal_roxybrowser_on_failure_sets_keepalive_for_roxybrowser_failure():
    class FakeApi:
        pass

    api = FakeApi()
    result = {"status": "failed"}

    assert (
        payment_checkout_browser.preserve_paypal_roxybrowser_on_failure(
            api,
            result,
            fallback_use_roxybrowser=True,
            keepalive_seconds=300,
        )
        is result
    )
    assert api._preserve_roxybrowser_on_stop is True
    assert api._preserve_roxybrowser_on_stop_seconds == 300


def test_preserve_paypal_roxybrowser_on_failure_skips_success():
    class FakeApi:
        pass

    api = FakeApi()

    assert payment_checkout_browser.preserve_paypal_roxybrowser_on_failure(
        api,
        {"status": "success"},
        fallback_use_roxybrowser=True,
        keepalive_seconds=300,
    ) == {"status": "success"}
    assert not hasattr(api, "_preserve_roxybrowser_on_stop")
    assert not hasattr(api, "_preserve_roxybrowser_on_stop_seconds")


def test_preserve_paypal_roxybrowser_on_failure_skips_non_roxybrowser_fallback():
    class FakeApi:
        pass

    api = FakeApi()

    assert payment_checkout_browser.preserve_paypal_roxybrowser_on_failure(
        api,
        {"status": "failed"},
        fallback_use_roxybrowser=False,
        keepalive_seconds=300,
    ) == {"status": "failed"}
    assert not hasattr(api, "_preserve_roxybrowser_on_stop")
    assert not hasattr(api, "_preserve_roxybrowser_on_stop_seconds")


def test_handle_paypal_pre_extracted_checkout_without_ba_skips_without_checkout_or_with_ba():
    assert (
        payment_checkout_browser.handle_paypal_pre_extracted_checkout_without_ba(
            {},
            safe_url_summary=lambda url: (_ for _ in ()).throw(AssertionError("summary should not run")),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
        )
        is None
    )
    assert (
        payment_checkout_browser.handle_paypal_pre_extracted_checkout_without_ba(
            {"checkout_url": "https://pay.openai.com/c/pay/cs_demo", "ba_token": "BA-DEMO"},
            safe_url_summary=lambda url: (_ for _ in ()).throw(AssertionError("summary should not run")),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
        )
        is None
    )


def test_handle_paypal_pre_extracted_checkout_without_ba_returns_failure_metadata_and_progress():
    progress_events = []

    result = payment_checkout_browser.handle_paypal_pre_extracted_checkout_without_ba(
        {
            "checkout_url": " https://pay.openai.com/c/pay/cs_demo ",
            "failure_stage": "extract_ba_link_poll",
            "message": "missing BA",
        },
        safe_url_summary=lambda url: f"summary:{url}",
        progress_event=lambda stage, *args, **extra: {"stage": stage, "args": args, **extra},
        on_progress=progress_events.append,
    )

    assert result == {
        "action": "failed",
        "failure_stage": "extract_ba_link_poll",
        "message": "missing BA",
        "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
    }
    assert progress_events == [
        {
            "stage": "paypal_protocol_checkout_without_ba",
            "args": ("协议模式已获取长 checkout 链接但未拿到 BA 链接，已停止浏览器回退",),
            "checkout_url": "summary:https://pay.openai.com/c/pay/cs_demo",
            "reason": "extract_ba_link_poll",
            "level": "warn",
        }
    ]


def test_handle_paypal_proxy_open_checkout_failure_skips_without_matching_failure_or_proxy():
    assert (
        payment_checkout_browser.handle_paypal_proxy_open_checkout_failure(
            {"failure_stage": "open_checkout"},
            proxy_url=None,
            is_tunnel_connection_error=lambda value: (_ for _ in ()).throw(AssertionError("tunnel should not run")),
            safe_url_summary=lambda url: (_ for _ in ()).throw(AssertionError("summary should not run")),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            logger=object(),
        )
        is None
    )
    assert (
        payment_checkout_browser.handle_paypal_proxy_open_checkout_failure(
            {"failure_stage": "paypal_authorize"},
            proxy_url="socks5://proxy.example:1080",
            is_tunnel_connection_error=lambda value: (_ for _ in ()).throw(AssertionError("tunnel should not run")),
            safe_url_summary=lambda url: (_ for _ in ()).throw(AssertionError("summary should not run")),
            progress_event=lambda stage, **extra: {"stage": stage, **extra},
            logger=object(),
        )
        is None
    )


def test_handle_paypal_proxy_open_checkout_failure_returns_default_proxy_failure_metadata():
    class FakeLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args):
            self.messages.append((message, args))

    logger = FakeLogger()
    progress_events = []

    result = payment_checkout_browser.handle_paypal_proxy_open_checkout_failure(
        {"failure_stage": "open_checkout", "message": "net failed"},
        proxy_url="socks5://proxy.example:1080",
        is_tunnel_connection_error=lambda value: False,
        safe_url_summary=lambda url: f"summary:{url}",
        progress_event=lambda stage, *args, **extra: {"stage": stage, "args": args, **extra},
        logger=logger,
        on_progress=progress_events.append,
    )

    assert result == {
        "action": "failed",
        "failure_stage": "open_checkout_proxy",
        "message": "代理打开 checkout 失败，已停止当前账号；不会切换直连重试: net failed",
    }
    assert progress_events == [
        {
            "stage": "paypal_proxy_open_checkout_failed",
            "args": ("代理打开 checkout 失败，已停止当前账号；不会切换直连重试",),
            "level": "warn",
        }
    ]
    assert logger.messages == [
        (
            "[paypal_bind_executor] checkout open failed with proxy, not retrying direct: proxy=%s",
            ("summary:socks5://proxy.example:1080",),
        )
    ]


def test_handle_paypal_proxy_open_checkout_failure_uses_tunnel_message_and_unknown_fallback():
    result = payment_checkout_browser.handle_paypal_proxy_open_checkout_failure(
        {"failure_stage": "open_checkout", "message": ""},
        proxy_url="socks5://proxy.example:1080",
        is_tunnel_connection_error=lambda value: True,
        safe_url_summary=lambda url: url,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        logger=type("Logger", (), {"info": lambda *_args, **_kwargs: None})(),
    )

    assert result == {
        "action": "failed",
        "failure_stage": "open_checkout_proxy",
        "message": "代理隧道打开 checkout 失败，已停止当前账号；不会切换直连重试: 未知错误",
    }


def test_handle_paypal_manual_pre_wait_autofill_skips_without_payload():
    assert (
        payment_checkout_browser.handle_paypal_manual_pre_wait_autofill(
            object(),
            autofill_payload=None,
            autofill_checkout_fields=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("autofill should not run")
            ),
        )
        is None
    )
    assert (
        payment_checkout_browser.handle_paypal_manual_pre_wait_autofill(
            object(),
            autofill_payload={},
            autofill_checkout_fields=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("autofill should not run")
            ),
        )
        is None
    )


def test_handle_paypal_manual_pre_wait_autofill_skips_when_disabled():
    assert (
        payment_checkout_browser.handle_paypal_manual_pre_wait_autofill(
            object(),
            autofill_payload={"name": "Taro Yamada"},
            autofill_enabled=False,
            autofill_checkout_fields=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("autofill should not run")
            ),
        )
        is None
    )


def test_handle_paypal_manual_pre_wait_autofill_dispatches_autofill_and_returns_metadata():
    api = object()
    payload = {"name": "Taro Yamada"}
    progress_events = []
    calls = []

    result = payment_checkout_browser.handle_paypal_manual_pre_wait_autofill(
        api,
        autofill_payload=payload,
        autofill_checkout_fields=lambda *args, **kwargs: calls.append((args, kwargs)),
        on_progress=progress_events.append,
    )

    assert result == {"action": "autofilled"}
    assert calls == [((api, payload), {"on_progress": progress_events.append})]


def test_handle_paypal_open_checkout_cancelled_skips_when_not_cancelled():
    assert payment_checkout_browser.handle_paypal_open_checkout_cancelled(is_cancelled=None) is None
    assert payment_checkout_browser.handle_paypal_open_checkout_cancelled(is_cancelled=lambda: False) is None


def test_handle_paypal_open_checkout_cancelled_returns_failed_metadata_when_cancelled():
    assert payment_checkout_browser.handle_paypal_open_checkout_cancelled(is_cancelled=lambda: True) == {
        "action": "failed",
        "failure_stage": "open_checkout",
        "message": "任务已取消",
    }


def test_launch_paypal_checkout_browser_uses_primary_browser_selection():
    captured = {}
    def on_progress(event):
        return None

    payment_checkout_browser.launch_paypal_checkout_browser(
        proxy_url="socks5://proxy.example:1080",
        proxy_bypass="localhost",
        use_fallback_browser=False,
        paypal_country="JP",
        paypal_lang="ja",
        use_camoufox=True,
        use_roxybrowser=False,
        fallback_use_camoufox=False,
        fallback_use_roxybrowser=True,
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        launch_browser=lambda **kwargs: captured.update(kwargs),
        on_progress=on_progress,
    )

    assert captured == {
        "proxy_url": "socks5://proxy.example:1080",
        "proxy_bypass": "localhost",
        "background": False,
        "locale": "ja-JP",
        "accept_language": "ja-JP,ja;q=0.9,en;q=0.8",
        "randomize_fingerprint": False,
        "use_camoufox": True,
        "use_roxybrowser": False,
        "roxybrowser_workspace_id": "workspace-1",
        "roxybrowser_profile_id": "profile-1",
        "on_progress": on_progress,
    }


def test_launch_paypal_checkout_browser_uses_fallback_browser_selection():
    captured = {}

    payment_checkout_browser.launch_paypal_checkout_browser(
        proxy_url=None,
        proxy_bypass=None,
        use_fallback_browser=True,
        paypal_country="US",
        paypal_lang="en",
        use_camoufox=False,
        use_roxybrowser=False,
        fallback_use_camoufox=False,
        fallback_use_roxybrowser=True,
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        launch_browser=lambda **kwargs: captured.update(kwargs),
    )

    assert captured["locale"] == "en-US"
    assert captured["accept_language"] == "en-US,en;q=0.9,en;q=0.8"
    assert captured["use_camoufox"] is False
    assert captured["use_roxybrowser"] is True
    assert captured["randomize_fingerprint"] is False


def test_handle_paypal_checkout_context_dispatch_returns_cancelled_result_before_prepare():
    calls = []
    def is_cancelled():
        return True

    result = payment_checkout_browser.handle_paypal_checkout_context_dispatch(
        object(),
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url=None,
        session_id="session-1",
        screenshot_paths=[],
        is_cancelled=is_cancelled,
        handle_open_checkout_cancelled=lambda **kwargs: (
            calls.append(("cancelled", kwargs))
            or {"action": "failed", "failure_stage": "open_checkout", "message": "任务已取消"}
        ),
        build_result=lambda *args, **kwargs: calls.append(("build", args, kwargs)) or {"status": args[0], **kwargs},
        prepare_chatgpt_checkout_context=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("prepare should not run")
        ),
        extract_auth_session_context=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("session context should not run")
        ),
        handle_proxy_open_checkout_failure=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("proxy failure should not run")
        ),
    )

    assert result == {
        "status": "failed",
        "failure_stage": "open_checkout",
        "message": "任务已取消",
    }
    assert calls == [
        ("cancelled", {"is_cancelled": is_cancelled}),
        (
            "build",
            ("failed",),
            {"failure_stage": "open_checkout", "message": "任务已取消"},
        ),
    ]


def test_handle_paypal_checkout_context_dispatch_builds_proxy_failure_result():
    api = object()
    screenshot_paths = []
    progress_events = []
    prepare_result = {"failure_stage": "open_checkout", "message": "net failed"}
    calls = []

    result = payment_checkout_browser.handle_paypal_checkout_context_dispatch(
        api,
        email=" user@example.com ",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        is_cancelled=None,
        handle_open_checkout_cancelled=lambda **kwargs: calls.append(("cancelled", kwargs)) or None,
        build_result=lambda *args, **kwargs: calls.append(("build", args, kwargs)) or {"status": args[0], **kwargs},
        prepare_chatgpt_checkout_context=lambda *args, **kwargs: (
            calls.append(("prepare", args, kwargs)) or prepare_result
        ),
        extract_auth_session_context=lambda email: calls.append(("session", email)) or {"token": "auth"},
        handle_proxy_open_checkout_failure=lambda value, **kwargs: (
            calls.append(("proxy", value, kwargs))
            or {"action": "failed", "failure_stage": "open_checkout_proxy", "message": "proxy failed"}
        ),
        on_progress=progress_events.append,
    )

    assert result == {
        "status": "failed",
        "failure_stage": "open_checkout_proxy",
        "message": "proxy failed",
        "screenshot_paths": screenshot_paths,
    }
    assert calls == [
        ("cancelled", {"is_cancelled": None}),
        ("session", "user@example.com"),
        (
            "prepare",
            (api,),
            {
                "email": "user@example.com",
                "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
                "session_context": {"token": "auth"},
                "session_id": "session-1",
                "screenshot_paths": screenshot_paths,
                "on_progress": progress_events.append,
            },
        ),
        (
            "proxy",
            prepare_result,
            {"proxy_url": "socks5://proxy.example:1080", "on_progress": progress_events.append},
        ),
        (
            "build",
            ("failed",),
            {
                "failure_stage": "open_checkout_proxy",
                "message": "proxy failed",
                "screenshot_paths": screenshot_paths,
            },
        ),
    ]


def test_handle_paypal_checkout_context_dispatch_returns_prepare_result_without_proxy_failure():
    prepare_result = {"status": "success", "failure_stage": "", "message": "prepared"}

    assert (
        payment_checkout_browser.handle_paypal_checkout_context_dispatch(
            object(),
            email="",
            checkout_url="https://pay.openai.com/c/pay/cs_demo",
            proxy_url=None,
            session_id="session-1",
            screenshot_paths=[],
            is_cancelled=None,
            handle_open_checkout_cancelled=lambda **_kwargs: None,
            build_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("build should not run")),
            prepare_chatgpt_checkout_context=lambda *_args, **_kwargs: prepare_result,
            extract_auth_session_context=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("session context should not run without email")
            ),
            handle_proxy_open_checkout_failure=lambda *_args, **_kwargs: None,
        )
        is prepare_result
    )


def test_handle_paypal_manual_result_wait_runs_autofill_then_waits_for_result():
    api = object()
    screenshot_paths = []
    progress_events = []
    payload = {"name": "Taro Yamada"}
    calls = []
    def is_cancelled():
        return False

    def fake_autofill(*args, **kwargs):
        calls.append(("autofill", args, kwargs))
        return {"action": "autofilled"}

    def fake_wait(*args, **kwargs):
        calls.append(("wait", args, kwargs))
        return {"status": "success"}

    result = payment_checkout_browser.handle_paypal_manual_result_wait(
        api,
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=payload,
        manual_pre_wait_autofill=fake_autofill,
        wait_for_paypal_result=fake_wait,
        on_progress=progress_events.append,
    )

    assert result == {"status": "success"}
    assert calls == [
        (
            "autofill",
            (api,),
            {"autofill_payload": payload, "autofill_enabled": True, "on_progress": progress_events.append},
        ),
        (
            "wait",
            (api,),
            {
                "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
                "proxy_url": "socks5://proxy.example:1080",
                "session_id": "session-1",
                "screenshot_paths": screenshot_paths,
                "timeout_seconds": 120,
                "is_cancelled": is_cancelled,
                "on_progress": progress_events.append,
                "autofill_enabled": True,
                "autofill_payload": payload,
            },
        ),
    ]


def test_handle_paypal_manual_result_wait_passes_disabled_autofill_flag_to_pre_wait_helper():
    api = object()
    screenshot_paths = []
    payload = {"name": "Taro Yamada"}
    calls = []

    result = payment_checkout_browser.handle_paypal_manual_result_wait(
        api,
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url=None,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=None,
        autofill_enabled=False,
        autofill_payload=payload,
        manual_pre_wait_autofill=lambda *args, **kwargs: calls.append(("autofill", args, kwargs)) or None,
        wait_for_paypal_result=lambda *args, **kwargs: calls.append(("wait", args, kwargs)) or {"status": "success"},
    )

    assert result == {"status": "success"}
    assert calls[0] == (
        "autofill",
        (api,),
        {"autofill_payload": payload, "autofill_enabled": False, "on_progress": None},
    )
    assert calls[1][0] == "wait"
    assert calls[1][2]["autofill_enabled"] is False
    assert calls[1][2]["autofill_payload"] is payload


def test_handle_paypal_post_checkout_flow_dispatch_returns_auto_flow_result():
    api = object()
    screenshot_paths = []
    progress_events = []
    phone_accounts = [{"phone": "+819012345678"}]
    payload = {"name": "Taro Yamada"}
    def is_cancelled():
        return False
    calls = []

    result = payment_checkout_browser.handle_paypal_post_checkout_flow_dispatch(
        api,
        auto_mode=True,
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=payload,
        handle_auto_flow_dispatch=lambda *args, **kwargs: calls.append(("auto", args, kwargs)) or {"status": "success"},
        handle_manual_result_wait=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("manual wait should not run")
        ),
        paypal_result_timeout_seconds=lambda *_args: (_ for _ in ()).throw(
            AssertionError("result timeout should not run")
        ),
        on_progress=progress_events.append,
    )

    assert result == {"status": "success"}
    assert calls == [
        (
            "auto",
            (api,),
            {
                "auto_mode": True,
                "email": "user@example.com",
                "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
                "proxy_url": "socks5://proxy.example:1080",
                "paypal_mode": "create_account",
                "paypal_country": "JP",
                "paypal_lang": "ja",
                "paypal_email": "paypal@example.com",
                "paypal_password": "secret",
                "sms_url": "https://sms.example.test",
                "otp_channel": "sms",
                "paypal_card_number": "4111111111111111",
                "paypal_card_expiry": "03/30",
                "paypal_card_cvv": "123",
                "phone_accounts": phone_accounts,
                "session_id": "session-1",
                "screenshot_paths": screenshot_paths,
                "timeout_seconds": 120,
                "is_cancelled": is_cancelled,
                "autofill_enabled": True,
                "autofill_payload": payload,
                "on_progress": progress_events.append,
            },
        )
    ]


def test_handle_paypal_post_checkout_flow_dispatch_falls_back_to_manual_result_wait():
    api = object()
    screenshot_paths = []
    progress_events = []
    payload = {"name": "Taro Yamada"}
    def is_cancelled():
        return False
    calls = []

    result = payment_checkout_browser.handle_paypal_post_checkout_flow_dispatch(
        api,
        auto_mode=False,
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url=None,
        paypal_mode="existing_account",
        paypal_country="US",
        paypal_lang="en",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="",
        otp_channel="sms",
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
        phone_accounts=[],
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=False,
        autofill_payload=payload,
        handle_auto_flow_dispatch=lambda *args, **kwargs: calls.append(("auto", args, kwargs)) or None,
        handle_manual_result_wait=lambda *args, **kwargs: (
            calls.append(("manual", args, kwargs)) or {"status": "needs_review"}
        ),
        paypal_result_timeout_seconds=lambda seconds: calls.append(("timeout", seconds)) or seconds + 5,
        on_progress=progress_events.append,
    )

    assert result == {"status": "needs_review"}
    assert calls[0][0] == "auto"
    assert calls[1] == ("timeout", 120)
    assert calls[2] == (
        "manual",
        (api,),
        {
            "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
            "proxy_url": None,
            "session_id": "session-1",
            "screenshot_paths": screenshot_paths,
            "timeout_seconds": 125,
            "is_cancelled": is_cancelled,
            "on_progress": progress_events.append,
            "autofill_enabled": False,
            "autofill_payload": payload,
        },
    )


def test_handle_paypal_unexpected_error_logs_captures_and_builds_failed_result():
    class Logger:
        def __init__(self):
            self.messages = []

        def exception(self, message):
            self.messages.append(message)

    api = object()
    logger = Logger()
    screenshot_paths = []
    calls = []
    exc = RuntimeError("boom")

    result = payment_checkout_browser.handle_paypal_unexpected_error(
        api,
        exc,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        logger=logger,
        capture_screenshot=lambda *args: calls.append(("screenshot", args)),
        build_result=lambda *args, **kwargs: calls.append(("build", args, kwargs)) or {"status": args[0], **kwargs},
    )

    assert result == {
        "status": "failed",
        "failure_stage": "post_submit",
        "message": "执行 PayPal 任务时出现异常: boom",
        "screenshot_paths": screenshot_paths,
    }
    assert logger.messages == ["[paypal_bind_executor] unexpected error"]
    assert calls == [
        ("screenshot", (api, "session-1", "paypal-unexpected-error", screenshot_paths)),
        (
            "build",
            ("failed",),
            {
                "failure_stage": "post_submit",
                "message": "执行 PayPal 任务时出现异常: boom",
                "screenshot_paths": screenshot_paths,
            },
        ),
    ]


def test_stop_paypal_api_safely_stops_api_and_swallows_errors():
    calls = []

    class Api:
        def stop(self):
            calls.append("stopped")

    payment_checkout_browser.stop_paypal_api_safely(Api())
    assert calls == ["stopped"]

    class FailingApi:
        def stop(self):
            calls.append("failing-stop")
            raise RuntimeError("stop failed")

    payment_checkout_browser.stop_paypal_api_safely(FailingApi())
    assert calls == ["stopped", "failing-stop"]


def test_prepare_paypal_auto_flow_payloads_resolves_checkout_then_signup_payload():
    calls = []
    autofill_payload = {"name": "Taro Yamada"}
    billing_payload = {"country": "JP", "name": "Taro Yamada"}
    signup_payload = {"country": "JP", "name": "タロウ ヤマダ"}

    result = payment_checkout_browser.prepare_paypal_auto_flow_payloads(
        autofill_payload=autofill_payload,
        autofill_enabled=True,
        paypal_country="JP",
        proxy_url="socks5://proxy.example:1080",
        resolve_checkout_billing_payload=lambda payload, **kwargs: (
            calls.append(("resolve", payload, kwargs)) or billing_payload
        ),
        prepare_signup_billing_payload=lambda payload, **kwargs: (
            calls.append(("prepare", payload, kwargs)) or signup_payload
        ),
    )

    assert result == {
        "billing_payload": billing_payload,
        "signup_billing_payload": signup_payload,
    }
    assert calls == [
        ("resolve", autofill_payload, {"auto_generate": True}),
        (
            "prepare",
            billing_payload,
            {
                "paypal_country": "JP",
                "proxy_url": "socks5://proxy.example:1080",
                "auto_generate": True,
            },
        ),
    ]


def test_prepare_paypal_auto_flow_identity_normalizes_credentials_and_builds_profile():
    calls = []
    signup_billing_payload = {"country": "JP", "name": "タロウ ヤマダ"}
    credentials = {"email": "paypal@example.com", "password": "secret"}
    profile = {"email": "paypal@example.com", "country": "JP"}

    result = payment_checkout_browser.prepare_paypal_auto_flow_identity(
        paypal_email="paypal@example.com",
        paypal_password="secret",
        signup_billing_payload=signup_billing_payload,
        paypal_country="JP",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        normalize_paypal_credentials=lambda email, password: (
            calls.append(("credentials", email, password)) or credentials
        ),
        build_paypal_signup_profile=lambda **kwargs: calls.append(("profile", kwargs)) or profile,
    )

    assert result == {
        "paypal_credentials": credentials,
        "signup_profile": profile,
    }
    assert calls == [
        ("credentials", "paypal@example.com", "secret"),
        (
            "profile",
            {
                "paypal_email": "paypal@example.com",
                "paypal_password": "secret",
                "billing_payload": signup_billing_payload,
                "paypal_country": "JP",
                "sms_url": "https://sms.example.test",
                "otp_channel": "sms",
                "paypal_card_number": "4111111111111111",
                "paypal_card_expiry": "03/30",
                "paypal_card_cvv": "123",
            },
        ),
    ]


def test_handle_paypal_auto_flow_dispatch_skips_when_not_auto_mode():
    assert (
        payment_checkout_browser.handle_paypal_auto_flow_dispatch(
            object(),
            auto_mode=False,
            email="user@example.com",
            checkout_url="https://pay.openai.com/c/pay/cs_demo",
            proxy_url=None,
            paypal_mode="login",
            paypal_country="US",
            paypal_lang="en",
            paypal_email="paypal@example.com",
            paypal_password="secret",
            sms_url="",
            otp_channel="sms",
            paypal_card_number="",
            paypal_card_expiry="",
            paypal_card_cvv="",
            phone_accounts=[],
            session_id="session-1",
            screenshot_paths=[],
            timeout_seconds=120,
            is_cancelled=None,
            autofill_enabled=False,
            autofill_payload=None,
            prepare_auto_flow_payloads=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("payloads should not run")
            ),
            prepare_auto_flow_identity=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("identity should not run")
            ),
            run_paypal_auto_flow=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("auto flow should not run")
            ),
        )
        is None
    )


def test_handle_paypal_auto_flow_dispatch_prepares_payloads_identity_and_runs_auto_flow():
    api = object()
    screenshot_paths = []
    progress_events = []
    autofill_payload = {"name": "Taro Yamada"}
    billing_payload = {"country": "JP"}
    signup_billing_payload = {"country": "JP", "name": "タロウ ヤマダ"}
    credentials = {"email": "paypal@example.com"}
    signup_profile = {"email": "paypal@example.com", "country": "JP"}
    phone_accounts = [{"phone": "+819012345678"}]
    def is_cancelled():
        return False
    calls = []

    result = payment_checkout_browser.handle_paypal_auto_flow_dispatch(
        api,
        auto_mode=True,
        email=" user@example.com ",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=autofill_payload,
        prepare_auto_flow_payloads=lambda **kwargs: (
            calls.append(("payloads", kwargs))
            or {
                "billing_payload": billing_payload,
                "signup_billing_payload": signup_billing_payload,
            }
        ),
        prepare_auto_flow_identity=lambda **kwargs: (
            calls.append(("identity", kwargs))
            or {
                "paypal_credentials": credentials,
                "signup_profile": signup_profile,
            }
        ),
        run_paypal_auto_flow=lambda *args, **kwargs: calls.append(("run", args, kwargs)) or {"status": "success"},
        on_progress=progress_events.append,
    )

    assert result == {"status": "success"}
    assert calls == [
        (
            "payloads",
            {
                "autofill_payload": autofill_payload,
                "autofill_enabled": True,
                "paypal_country": "JP",
                "proxy_url": "socks5://proxy.example:1080",
            },
        ),
        (
            "identity",
            {
                "paypal_email": "paypal@example.com",
                "paypal_password": "secret",
                "signup_billing_payload": signup_billing_payload,
                "paypal_country": "JP",
                "sms_url": "https://sms.example.test",
                "otp_channel": "sms",
                "paypal_card_number": "4111111111111111",
                "paypal_card_expiry": "03/30",
                "paypal_card_cvv": "123",
            },
        ),
        (
            "run",
            (api,),
            {
                "email": "user@example.com",
                "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
                "proxy_url": "socks5://proxy.example:1080",
                "paypal_mode": "create_account",
                "paypal_country": "JP",
                "paypal_lang": "ja",
                "paypal_credentials": credentials,
                "signup_profile": signup_profile,
                "phone_accounts": phone_accounts,
                "billing_payload": billing_payload,
                "session_id": "session-1",
                "screenshot_paths": screenshot_paths,
                "timeout_seconds": 120,
                "is_cancelled": is_cancelled,
                "on_progress": progress_events.append,
                "autofill_enabled": True,
                "autofill_payload": autofill_payload,
            },
        ),
    ]


def test_handle_paypal_auto_flow_checkout_handoff_skips_non_checkout_url():
    assert (
        payment_checkout_browser.handle_paypal_auto_flow_checkout_handoff(
            object(),
            current_url="https://www.paypal.com/checkoutnow",
            email="user@example.com",
            billing_payload={},
            session_id="session-1",
            screenshot_paths=[],
            timeout_seconds=120,
            is_cancelled=None,
            progress=lambda *_args, **_kwargs: None,
            is_checkout_host=lambda _url: False,
            page_url=lambda: (_ for _ in ()).throw(AssertionError("page URL should not be read")),
            browser_checkout_nonzero_amount_hint=lambda _api: (_ for _ in ()).throw(
                AssertionError("charge guard should not run")
            ),
            capture_screenshot=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("screenshot should not run")
            ),
            build_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("result should not be built")),
            select_paypal_option=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("PayPal option should not be selected")
            ),
            autofill_allowed=lambda _url: False,
            has_complete_billing_payload=lambda _payload: False,
            emit_progress=lambda *_args, **_kwargs: None,
            progress_event=lambda *_args, **_kwargs: {},
            fill_paypal_checkout_billing_form=lambda *_args, **_kwargs: (True, ""),
            accept_checkout_terms_on_page=lambda *_args, **_kwargs: None,
            submit_checkout_to_paypal=lambda *_args, **_kwargs: None,
        )
        is None
    )


def test_handle_paypal_auto_flow_checkout_handoff_blocks_nonzero_checkout_amount():
    screenshots = []
    build_calls = []

    result = payment_checkout_browser.handle_paypal_auto_flow_checkout_handoff(
        object(),
        current_url="https://pay.openai.com/c/pay/cs_demo",
        email="user@example.com",
        billing_payload={"country": "US"},
        session_id="session-1",
        screenshot_paths=screenshots,
        timeout_seconds=120,
        is_cancelled=None,
        progress=lambda *_args, **_kwargs: None,
        is_checkout_host=lambda _url: True,
        page_url=lambda: "https://pay.openai.com/c/pay/cs_demo",
        browser_checkout_nonzero_amount_hint=lambda _api: "$20.00",
        capture_screenshot=lambda _api, session_id, label, paths: screenshots.append((session_id, label, paths)),
        build_result=lambda status, **kwargs: build_calls.append((status, kwargs)) or {"status": status, **kwargs},
        select_paypal_option=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("PayPal option should not be selected")
        ),
        autofill_allowed=lambda _url: False,
        has_complete_billing_payload=lambda _payload: False,
        emit_progress=lambda *_args, **_kwargs: None,
        progress_event=lambda *_args, **_kwargs: {},
        fill_paypal_checkout_billing_form=lambda *_args, **_kwargs: (True, ""),
        accept_checkout_terms_on_page=lambda *_args, **_kwargs: None,
        submit_checkout_to_paypal=lambda *_args, **_kwargs: None,
    )

    assert result["status"] == "failed"
    assert result["failure_stage"] == "browser_charge_guard"
    assert "$20.00" in result["message"]
    assert screenshots == [("session-1", "paypal-browser-nonzero-amount-blocked", screenshots)]
    assert build_calls[0][0] == "failed"


def test_handle_paypal_auto_flow_checkout_handoff_fills_and_submits_checkout():
    api = object()
    screenshot_paths = []
    billing_payload = {"name": "Taro Yamada", "country": "JP"}
    def is_cancelled():
        return False
    emitted_events = []
    progress_calls = []
    calls = []
    on_progress = emitted_events.append
    def progress(stage, **kwargs):
        return progress_calls.append((stage, kwargs))

    result = payment_checkout_browser.handle_paypal_auto_flow_checkout_handoff(
        api,
        current_url="https://pay.openai.com/c/pay/cs_demo",
        email="user@example.com",
        billing_payload=billing_payload,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=180,
        is_cancelled=is_cancelled,
        progress=progress,
        is_checkout_host=lambda url: calls.append(("is_checkout_host", url)) or True,
        page_url=lambda: "https://pay.openai.com/c/pay/cs_demo",
        browser_checkout_nonzero_amount_hint=lambda _api: calls.append(("charge_guard", _api)) or "",
        capture_screenshot=lambda *_args, **_kwargs: calls.append(("screenshot", _args, _kwargs)),
        build_result=lambda status, **kwargs: {"status": status, **kwargs},
        select_paypal_option=lambda _api, **kwargs: calls.append(("select", _api, kwargs)) or True,
        autofill_allowed=lambda url: calls.append(("autofill_allowed", url)) or True,
        has_complete_billing_payload=lambda payload: calls.append(("complete_payload", payload)) or True,
        emit_progress=lambda callback, event: calls.append(("emit", callback, event)) or callback(event),
        progress_event=lambda stage, **kwargs: {"stage": stage, **kwargs},
        fill_paypal_checkout_billing_form=lambda _api, payload, session_id, paths, **kwargs: (
            calls.append(("fill", _api, payload, session_id, paths, kwargs)) or (True, "")
        ),
        accept_checkout_terms_on_page=lambda _api, **kwargs: calls.append(("accept_terms", _api, kwargs)),
        submit_checkout_to_paypal=lambda _api, **kwargs: (
            calls.append(("submit", _api, kwargs)) or {"status": "needs_review"}
        ),
        on_progress=on_progress,
    )

    assert result == {"status": "needs_review"}
    assert emitted_events == [
        {
            "stage": "paypal_billing_fill_started",
            "url": "https://pay.openai.com/c/pay/cs_demo",
            "billing_info": billing_payload,
        },
        {"stage": "paypal_billing_fill_done", "url": "https://pay.openai.com/c/pay/cs_demo"},
    ]
    assert ("is_checkout_host", "https://pay.openai.com/c/pay/cs_demo") in calls
    assert ("charge_guard", api) in calls
    assert ("select", api, {"on_progress": on_progress}) in calls
    assert ("complete_payload", billing_payload) in calls
    assert ("accept_terms", api, {"progress": progress}) in calls
    assert (
        "submit",
        api,
        {
            "email": "user@example.com",
            "session_id": "session-1",
            "screenshot_paths": screenshot_paths,
            "timeout_seconds": 90,
            "is_cancelled": is_cancelled,
            "on_progress": on_progress,
        },
    ) in calls
    assert progress_calls == []


def test_run_paypal_auto_flow_sequence_returns_handoff_after_context_preparation():
    api = object()
    screenshot_paths = []
    autofill_payload = {"name": "Taro Yamada"}
    progress = object()
    def on_progress(event):
        return None
    def is_cancelled():
        return False
    calls = []

    result = payment_checkout_browser.run_paypal_auto_flow_sequence(
        api,
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        paypal_mode="create_account",
        paypal_credentials={"email": "paypal@example.com"},
        signup_profile={"email": "paypal@example.com"},
        phone_accounts=[],
        billing_payload=None,
        paypal_country="",
        paypal_lang="",
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=180,
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=autofill_payload,
        page_url=lambda: "https://pay.openai.com/c/pay/cs_demo",
        resolve_checkout_billing_payload=lambda payload, **kwargs: (
            calls.append(("resolve", payload, kwargs)) or {"country": " jp ", "name": "Taro Yamada"}
        ),
        normalize_paypal_country=lambda country: calls.append(("country", country)) or "JP",
        normalize_paypal_lang=lambda lang, country: calls.append(("lang", lang, country)) or "ja",
        progress_adapter=lambda callback: calls.append(("progress", callback)) or progress,
        handle_checkout_handoff=lambda _api, **kwargs: calls.append(("handoff", _api, kwargs)) or {"status": "handoff"},
        run_paypal_authorize_flow=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("authorize should not run")
        ),
        paypal_authorize_timeout_seconds=lambda seconds: calls.append(("authorize_timeout", seconds)) or seconds + 1,
        wait_for_paypal_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
        paypal_result_timeout_seconds=lambda seconds: calls.append(("result_timeout", seconds)) or seconds + 2,
        on_progress=on_progress,
    )

    assert result == {"status": "handoff"}
    assert calls[:5] == [
        ("resolve", autofill_payload, {"auto_generate": True}),
        ("country", " jp "),
        ("lang", "", "JP"),
        ("progress", on_progress),
        ("authorize_timeout", 180),
    ]
    assert calls[5] == ("result_timeout", 180)
    assert calls[6][0] == "handoff"
    assert calls[6][1] is api
    assert calls[6][2] == {
        "current_url": "https://pay.openai.com/c/pay/cs_demo",
        "email": "user@example.com",
        "billing_payload": {"country": " jp ", "name": "Taro Yamada"},
        "session_id": "session-1",
        "screenshot_paths": screenshot_paths,
        "timeout_seconds": 180,
        "is_cancelled": is_cancelled,
        "progress": progress,
        "on_progress": on_progress,
    }


def test_run_paypal_auto_flow_sequence_authorizes_then_waits_for_result():
    api = object()
    screenshot_paths = []
    billing_payload = {"country": "US"}
    paypal_credentials = {"email": "paypal@example.com"}
    signup_profile = {"email": "paypal@example.com"}
    phone_accounts = [{"phone": "+12025550123"}]
    def is_cancelled():
        return False
    def on_progress(event):
        return None
    calls = []

    result = payment_checkout_browser.run_paypal_auto_flow_sequence(
        api,
        email="user@example.com",
        checkout_url="",
        proxy_url=None,
        paypal_mode="login",
        paypal_credentials=paypal_credentials,
        signup_profile=signup_profile,
        phone_accounts=phone_accounts,
        billing_payload=billing_payload,
        paypal_country="ca",
        paypal_lang="fr",
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=False,
        autofill_payload=None,
        page_url=lambda: "https://pay.openai.com/c/pay/cs_demo",
        resolve_checkout_billing_payload=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("billing payload should not be resolved")
        ),
        normalize_paypal_country=lambda country: calls.append(("country", country)) or "CA",
        normalize_paypal_lang=lambda lang, country: calls.append(("lang", lang, country)) or "fr",
        progress_adapter=lambda callback: calls.append(("progress", callback)) or (lambda *_args, **_kwargs: None),
        handle_checkout_handoff=lambda _api, **kwargs: calls.append(("handoff", _api, kwargs)) or None,
        run_paypal_authorize_flow=lambda _api, **kwargs: calls.append(("authorize", _api, kwargs)) or None,
        paypal_authorize_timeout_seconds=lambda seconds: calls.append(("authorize_timeout", seconds)) or seconds + 10,
        wait_for_paypal_result=lambda _api, **kwargs: calls.append(("wait", _api, kwargs)) or {"status": "success"},
        paypal_result_timeout_seconds=lambda seconds: calls.append(("result_timeout", seconds)) or seconds + 20,
        on_progress=on_progress,
    )

    assert result == {"status": "success"}
    assert ("country", "ca") in calls
    assert ("lang", "fr", "CA") in calls
    assert calls[-2][0] == "authorize"
    assert calls[-2][1] is api
    assert calls[-2][2] == {
        "paypal_mode": "login",
        "paypal_country": "CA",
        "paypal_lang": "fr",
        "credentials": paypal_credentials,
        "signup_profile": signup_profile,
        "session_id": "session-1",
        "screenshot_paths": screenshot_paths,
        "timeout_seconds": 130,
        "is_cancelled": is_cancelled,
        "on_progress": on_progress,
        "phone_accounts": phone_accounts,
    }
    assert calls[-1] == (
        "wait",
        api,
        {
            "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
            "proxy_url": None,
            "session_id": "session-1",
            "screenshot_paths": screenshot_paths,
            "timeout_seconds": 140,
            "is_cancelled": is_cancelled,
            "on_progress": on_progress,
            "autofill_enabled": False,
            "autofill_payload": None,
        },
    )


def test_handle_paypal_protocol_flow_dispatch_prepares_payloads_profile_and_runs_protocol_flow():
    progress_events = []
    autofill_payload = {"name": "Taro Yamada"}
    billing_payload = {"country": "JP"}
    signup_billing_payload = {"country": "JP", "name": "タロウ ヤマダ"}
    signup_profile = {"email": "paypal@example.com", "country": "JP"}
    phone_accounts = [{"phone": "+819012345678"}]
    pre_extracted = None
    def is_cancelled():
        return False
    protocol_result = {"status": "needs_review", "paypal_approve_url": "https://www.paypal.com/agreements/approve"}
    calls = []

    result = payment_checkout_browser.handle_paypal_protocol_flow_dispatch(
        email=" user@example.com ",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        autofill_enabled=True,
        autofill_payload=autofill_payload,
        pre_extracted=pre_extracted,
        prepare_auto_flow_payloads=lambda **kwargs: (
            calls.append(("payloads", kwargs))
            or {
                "billing_payload": billing_payload,
                "signup_billing_payload": signup_billing_payload,
            }
        ),
        build_paypal_signup_profile=lambda **kwargs: calls.append(("profile", kwargs)) or signup_profile,
        run_paypal_protocol_flow=lambda **kwargs: calls.append(("run", kwargs)) or protocol_result,
        on_progress=progress_events.append,
    )

    assert result == {
        "billing_payload": billing_payload,
        "signup_billing_payload": signup_billing_payload,
        "protocol_result": protocol_result,
    }
    assert calls == [
        (
            "payloads",
            {
                "autofill_payload": autofill_payload,
                "autofill_enabled": True,
                "paypal_country": "JP",
                "proxy_url": "socks5://proxy.example:1080",
            },
        ),
        (
            "profile",
            {
                "paypal_email": "paypal@example.com",
                "paypal_password": "secret",
                "billing_payload": signup_billing_payload,
                "paypal_country": "JP",
                "sms_url": "https://sms.example.test",
                "otp_channel": "sms",
                "phone_accounts": phone_accounts,
                "paypal_card_number": "4111111111111111",
                "paypal_card_expiry": "03/30",
                "paypal_card_cvv": "123",
            },
        ),
        (
            "run",
            {
                "email": "user@example.com",
                "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
                "proxy_url": "socks5://proxy.example:1080",
                "paypal_mode": "create_account",
                "paypal_country": "JP",
                "paypal_lang": "ja",
                "signup_profile": signup_profile,
                "phone_accounts": phone_accounts,
                "billing_payload": billing_payload,
                "timeout_seconds": 120,
                "is_cancelled": is_cancelled,
                "on_progress": progress_events.append,
                "pre_extracted": pre_extracted,
            },
        ),
    ]


def test_handle_paypal_protocol_browser_fallback_dispatch_authorizes_then_waits_for_result():
    class Api:
        page = "initial-page"

    api = Api()
    fallback_context = {"browser_entry_url": "https://www.paypal.com/signin?ba_token=BA-DEMO"}
    signup_billing_payload = {"country": "JP"}
    credentials = {"email": "paypal@example.com"}
    signup_profile = {"email": "paypal@example.com", "country": "JP"}
    phone_accounts = [{"phone": "+819012345678"}]
    screenshot_paths = []
    def is_cancelled():
        return False
    calls = []

    def launch_browser(**kwargs):
        calls.append(("launch", kwargs))
        api.page = "fallback-page"

    def emit_progress(callback, event):
        calls.append(("progress", callback, event))

    result = payment_checkout_browser.handle_paypal_protocol_browser_fallback_dispatch(
        api,
        fallback_context=fallback_context,
        fallback_approve_url="https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
        fallback_ba_token="BA-DEMO",
        proxy_url="socks5://proxy.example:1080",
        proxy_bypass="localhost",
        fallback_use_camoufox=True,
        fallback_use_roxybrowser=False,
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        signup_billing_payload=signup_billing_payload,
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        timeout_seconds=120,
        is_cancelled=is_cancelled,
        launch_browser=launch_browser,
        emit_progress=emit_progress,
        progress_event=lambda stage, **kwargs: {"stage": stage, **kwargs},
        goto_paypal_page_with_retries=lambda *args, **kwargs: calls.append(("goto", args, kwargs)),
        handle_browser_fallback_ddc_wait=lambda *args, **kwargs: (
            calls.append(("ddc", args, kwargs)) or {"action": "continue"}
        ),
        build_result=lambda *args, **kwargs: calls.append(("build_result", args, kwargs)) or {"status": "failed"},
        preserve_roxybrowser_on_failure=lambda result: calls.append(("preserve", result)) or result,
        ensure_captcha_bypass=lambda _api: calls.append(("captcha", _api)),
        normalize_paypal_credentials=lambda email, password: (
            calls.append(("credentials", email, password)) or credentials
        ),
        build_paypal_signup_profile=lambda **kwargs: calls.append(("profile", kwargs)) or signup_profile,
        run_paypal_authorize_flow=lambda *args, **kwargs: calls.append(("authorize", args, kwargs)) or None,
        paypal_authorize_timeout_seconds=lambda seconds: seconds + 1,
        wait_for_paypal_result=lambda *args, **kwargs: calls.append(("wait", args, kwargs)) or {"status": "success"},
        paypal_result_timeout_seconds=lambda seconds: seconds + 2,
        on_progress=list().append,
    )

    assert result == {"status": "success"}
    assert calls[0] == (
        "launch",
        {
            "proxy_url": "socks5://proxy.example:1080",
            "proxy_bypass": "localhost",
            "background": False,
            "locale": "ja-JP",
            "accept_language": "ja-JP,ja;q=0.9,en;q=0.8",
            "use_camoufox": True,
            "use_roxybrowser": False,
            "roxybrowser_workspace_id": "workspace-1",
            "roxybrowser_profile_id": "profile-1",
            "on_progress": calls[1][1] if len(calls) > 1 else None,
        },
    )
    assert calls[1][0] == "progress"
    assert calls[1][2] == {"stage": "paypal_browser_fallback_navigate"}
    assert calls[2] == (
        "goto",
        ("fallback-page", "https://www.paypal.com/signin?ba_token=BA-DEMO"),
        {"on_progress": calls[1][1], "attempts": 3, "timeout_ms": 60000},
    )
    assert calls[3][0] == "progress"
    assert calls[3][2] == {"stage": "paypal_browser_fallback_ddc_wait"}
    assert calls[4] == ("ddc", ("fallback-page",), {"on_progress": calls[1][1]})
    assert calls[5] == ("captcha", api)
    assert calls[6] == ("credentials", "paypal@example.com", "secret")
    assert calls[7] == (
        "profile",
        {
            "paypal_email": "paypal@example.com",
            "paypal_password": "secret",
            "billing_payload": signup_billing_payload,
            "paypal_country": "JP",
            "sms_url": "https://sms.example.test",
            "otp_channel": "sms",
            "phone_accounts": phone_accounts,
            "paypal_card_number": "4111111111111111",
            "paypal_card_expiry": "03/30",
            "paypal_card_cvv": "123",
        },
    )
    assert calls[8][0] == "authorize"
    assert calls[8][1] == (api,)
    assert calls[8][2]["paypal_ba_token"] == "BA-DEMO"
    assert calls[8][2]["credentials"] is credentials
    assert calls[8][2]["signup_profile"] is signup_profile
    assert calls[8][2]["timeout_seconds"] == 121
    assert calls[9][0] == "wait"
    assert calls[9][2]["timeout_seconds"] == 122
    assert calls[9][2]["autofill_enabled"] is False
    assert calls[9][2]["autofill_payload"] is None
    assert calls[10] == ("preserve", {"status": "success"})


def test_handle_paypal_protocol_browser_fallback_dispatch_returns_preserved_ddc_failure():
    class Api:
        page = "fallback-page"

    calls = []

    result = payment_checkout_browser.handle_paypal_protocol_browser_fallback_dispatch(
        Api(),
        fallback_context={},
        fallback_approve_url="https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
        fallback_ba_token="BA-DEMO",
        proxy_url=None,
        proxy_bypass=None,
        fallback_use_camoufox=False,
        fallback_use_roxybrowser=True,
        roxybrowser_workspace_id="",
        roxybrowser_profile_id="",
        paypal_mode="create_account",
        paypal_country="US",
        paypal_lang="en",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="",
        otp_channel="sms",
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
        phone_accounts=[],
        signup_billing_payload={},
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        session_id="session-1",
        screenshot_paths=[],
        timeout_seconds=120,
        is_cancelled=None,
        launch_browser=lambda **kwargs: calls.append(("launch", kwargs)),
        emit_progress=lambda callback, event: calls.append(("progress", event)),
        progress_event=lambda stage, **kwargs: {"stage": stage, **kwargs},
        goto_paypal_page_with_retries=lambda *args, **kwargs: calls.append(("goto", args, kwargs)),
        handle_browser_fallback_ddc_wait=lambda *args, **kwargs: {"action": "failed", "message": "blocked"},
        build_result=lambda *args, **kwargs: (
            calls.append(("build_result", args, kwargs)) or {"status": args[0], **kwargs}
        ),
        preserve_roxybrowser_on_failure=lambda result: calls.append(("preserve", result)) or result,
        ensure_captcha_bypass=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("captcha should not run")),
        normalize_paypal_credentials=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("credentials should not run")
        ),
        build_paypal_signup_profile=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("profile should not run")),
        run_paypal_authorize_flow=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("authorize should not run")
        ),
        paypal_authorize_timeout_seconds=lambda seconds: seconds,
        wait_for_paypal_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
        paypal_result_timeout_seconds=lambda seconds: seconds,
    )

    assert result == {
        "status": "failed",
        "failure_stage": "paypal_datadome_blocked",
        "message": "blocked",
    }
    assert calls[-2] == (
        "build_result",
        ("failed",),
        {"failure_stage": "paypal_datadome_blocked", "message": "blocked"},
    )
    assert calls[-1] == ("preserve", result)


def test_handle_paypal_protocol_browser_fallback_dispatch_relaunches_closed_roxy_page():
    class Api:
        page = None

    api = Api()
    calls = []
    progress_events = []

    def launch_browser(**kwargs):
        calls.append(("launch", kwargs))
        api.page = f"page-{len([call for call in calls if call[0] == 'launch'])}"

    def goto_paypal_page_with_retries(page, url, **kwargs):
        calls.append(("goto", page, url, kwargs))
        if page == "page-1":
            raise RuntimeError("Page.goto: Target page, context or browser has been closed")

    result = payment_checkout_browser.handle_paypal_protocol_browser_fallback_dispatch(
        api,
        fallback_context={},
        fallback_approve_url="https://www.paypal.com/agreements/approve?ba_token=BA-DEMO",
        fallback_ba_token="BA-DEMO",
        proxy_url=None,
        proxy_bypass=None,
        fallback_use_camoufox=False,
        fallback_use_roxybrowser=True,
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="stale-profile",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="",
        otp_channel="sms",
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
        phone_accounts=[],
        signup_billing_payload={},
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        session_id="session-1",
        screenshot_paths=[],
        timeout_seconds=120,
        is_cancelled=None,
        launch_browser=launch_browser,
        emit_progress=lambda callback, event: progress_events.append(event),
        progress_event=lambda stage, **kwargs: {"stage": stage, **kwargs},
        goto_paypal_page_with_retries=goto_paypal_page_with_retries,
        handle_browser_fallback_ddc_wait=lambda page, **kwargs: calls.append(("ddc", page, kwargs)) or {"action": "continue"},
        build_result=lambda *args, **kwargs: {"status": "failed"},
        preserve_roxybrowser_on_failure=lambda result: result,
        ensure_captcha_bypass=lambda _api: calls.append(("captcha", _api)),
        normalize_paypal_credentials=lambda email, password: {"email": email, "password": password},
        build_paypal_signup_profile=lambda **kwargs: {},
        run_paypal_authorize_flow=lambda *args, **kwargs: None,
        paypal_authorize_timeout_seconds=lambda seconds: seconds,
        wait_for_paypal_result=lambda *args, **kwargs: {"status": "success"},
        paypal_result_timeout_seconds=lambda seconds: seconds,
        on_progress=progress_events.append,
    )

    assert result == {"status": "success"}
    launch_calls = [call for call in calls if call[0] == "launch"]
    assert len(launch_calls) == 2
    assert launch_calls[0][1]["roxybrowser_profile_id"] == "stale-profile"
    assert launch_calls[1][1]["roxybrowser_profile_id"] == ""
    assert "roxybrowser_force_new_profile" not in launch_calls[1][1]
    assert ("goto", "page-1", "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO", {"on_progress": progress_events.append, "attempts": 3, "timeout_ms": 60000}) in calls
    assert ("goto", "page-2", "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO", {"on_progress": progress_events.append, "attempts": 3, "timeout_ms": 60000}) in calls
    assert any(event.get("stage") == "paypal_roxybrowser_closed_relaunch" for event in progress_events)
    assert ("ddc", "page-2", {"on_progress": progress_events.append}) in calls


def test_handle_paypal_protocol_mode_dispatch_skips_when_not_protocol_mode():
    assert (
        payment_checkout_browser.handle_paypal_protocol_mode_dispatch(
            object(),
            protocol_mode=False,
            pre_extracted=None,
            email="user@example.com",
            checkout_url="https://pay.openai.com/c/pay/cs_demo",
            proxy_url=None,
            proxy_bypass=None,
            paypal_mode="existing_account",
            paypal_country="US",
            paypal_lang="en",
            paypal_email="paypal@example.com",
            paypal_password="secret",
            sms_url="",
            otp_channel="sms",
            paypal_card_number="",
            paypal_card_expiry="",
            paypal_card_cvv="",
            phone_accounts=[],
            timeout_seconds=120,
            is_cancelled=None,
            autofill_enabled=False,
            autofill_payload=None,
            session_id="session-1",
            screenshot_paths=[],
            fallback_use_camoufox=True,
            fallback_use_roxybrowser=False,
            roxybrowser_workspace_id="",
            roxybrowser_profile_id="",
            handle_pre_extracted_checkout_without_ba=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("pre-extracted should not run")
            ),
            build_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("build should not run")),
            prepare_auto_flow_payloads=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("payload prep should not run")
            ),
            handle_protocol_flow_dispatch=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("protocol flow should not run")
            ),
            paypal_protocol_needs_browser_fallback=lambda *_args: (_ for _ in ()).throw(
                AssertionError("fallback check should not run")
            ),
            handle_protocol_browser_fallback_context=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("fallback context should not run")
            ),
            handle_protocol_browser_fallback_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("fallback dispatch should not run")
            ),
        )
        is None
    )


def test_handle_paypal_protocol_mode_dispatch_builds_pre_extracted_without_ba_result():
    pre_extracted = {"checkout_url": "https://pay.openai.com/c/pay/cs_demo"}
    calls = []

    result = payment_checkout_browser.handle_paypal_protocol_mode_dispatch(
        object(),
        protocol_mode=True,
        pre_extracted=pre_extracted,
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url=None,
        proxy_bypass=None,
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=[],
        timeout_seconds=120,
        is_cancelled=None,
        autofill_enabled=False,
        autofill_payload=None,
        session_id="session-1",
        screenshot_paths=[],
        fallback_use_camoufox=True,
        fallback_use_roxybrowser=False,
        roxybrowser_workspace_id="",
        roxybrowser_profile_id="",
        handle_pre_extracted_checkout_without_ba=lambda value, **kwargs: (
            calls.append(("pre", value, kwargs))
            or {
                "action": "failed",
                "failure_stage": "extract_ba_link_poll",
                "message": "missing BA",
                "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
            }
        ),
        build_result=lambda *args, **kwargs: calls.append(("build", args, kwargs)) or {"status": args[0], **kwargs},
        prepare_auto_flow_payloads=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("payload prep should not run")
        ),
        handle_protocol_flow_dispatch=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("protocol flow should not run")
        ),
        paypal_protocol_needs_browser_fallback=lambda *_args: (_ for _ in ()).throw(
            AssertionError("fallback check should not run")
        ),
        handle_protocol_browser_fallback_context=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fallback context should not run")
        ),
        handle_protocol_browser_fallback_dispatch=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fallback dispatch should not run")
        ),
    )

    assert result == {
        "status": "failed",
        "failure_stage": "extract_ba_link_poll",
        "message": "missing BA",
        "checkout_url": "https://pay.openai.com/c/pay/cs_demo",
    }
    assert calls == [
        ("pre", pre_extracted, {"on_progress": None}),
        (
            "build",
            ("failed",),
            {"failure_stage": "extract_ba_link_poll", "message": "missing BA"},
        ),
    ]


def test_handle_paypal_pre_extracted_checkout_without_ba_stops_failed_ba_without_checkout_url():
    events = []

    result = payment_checkout_browser.handle_paypal_pre_extracted_checkout_without_ba(
        {
            "status": "failed",
            "failure_stage": "extract_ba_link_poll",
            "message": "setup_intent requires_payment_method",
        },
        safe_url_summary=lambda value: f"safe:{value}",
        progress_event=lambda stage, message="", **kwargs: {"stage": stage, "message": message, **kwargs},
        on_progress=events.append,
    )

    assert result == {
        "action": "failed",
        "failure_stage": "extract_ba_link_poll",
        "message": "setup_intent requires_payment_method",
        "checkout_url": "",
    }
    assert events == [
        {
            "stage": "paypal_protocol_checkout_without_ba",
            "message": "协议模式已获取长 checkout 链接但未拿到 BA 链接，已停止浏览器回退",
            "checkout_url": "safe:",
            "reason": "extract_ba_link_poll",
            "level": "warn",
        }
    ]


def test_handle_paypal_protocol_mode_dispatch_runs_browser_fallback():
    api = object()
    progress_events = []
    screenshot_paths = []
    phone_accounts = [{"phone": "+819012345678"}]
    pre_extracted = None
    autofill_payload = {"name": "Taro Yamada"}
    signup_billing_payload = {"country": "JP"}
    protocol_result = {"status": "needs_review", "paypal_approve_url": "https://www.paypal.com/approve"}
    fallback_context = {
        "action": "fallback",
        "paypal_approve_url": "https://www.paypal.com/approve",
        "ba_token": "BA-DEMO",
        "browser_entry_url": "https://www.paypal.com/signin",
    }
    calls = []

    result = payment_checkout_browser.handle_paypal_protocol_mode_dispatch(
        api,
        protocol_mode=True,
        pre_extracted=pre_extracted,
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url="socks5://proxy.example:1080",
        proxy_bypass="localhost",
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="paypal@example.com",
        paypal_password="secret",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="4111111111111111",
        paypal_card_expiry="03/30",
        paypal_card_cvv="123",
        phone_accounts=phone_accounts,
        timeout_seconds=120,
        is_cancelled=None,
        autofill_enabled=True,
        autofill_payload=autofill_payload,
        session_id="session-1",
        screenshot_paths=screenshot_paths,
        fallback_use_camoufox=True,
        fallback_use_roxybrowser=True,
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        handle_pre_extracted_checkout_without_ba=lambda value, **kwargs: calls.append(("pre", value, kwargs)) or None,
        build_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("build should not run")),
        prepare_auto_flow_payloads=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("normal fallback receives payloads from protocol dispatch")
        ),
        handle_protocol_flow_dispatch=lambda **kwargs: (
            calls.append(("protocol", kwargs))
            or {"signup_billing_payload": signup_billing_payload, "protocol_result": protocol_result}
        ),
        paypal_protocol_needs_browser_fallback=lambda value: calls.append(("needs_fallback", value)) or True,
        handle_protocol_browser_fallback_context=lambda value, **kwargs: (
            calls.append(("context", value, kwargs)) or fallback_context
        ),
        handle_protocol_browser_fallback_dispatch=lambda *args, **kwargs: (
            calls.append(("fallback", args, kwargs)) or {"status": "success"}
        ),
        on_progress=progress_events.append,
    )

    assert result == {"status": "success"}
    assert calls[0] == ("pre", pre_extracted, {"on_progress": progress_events.append})
    assert calls[1][0] == "protocol"
    assert calls[1][1]["pre_extracted"] is pre_extracted
    assert calls[1][1]["autofill_payload"] is autofill_payload
    assert calls[2] == ("needs_fallback", protocol_result)
    assert calls[3] == (
        "context",
        protocol_result,
        {
            "paypal_mode": "create_account",
            "paypal_country": "JP",
            "paypal_lang": "ja",
            "on_progress": progress_events.append,
        },
    )
    assert calls[4][0] == "fallback"
    assert calls[4][1] == (api,)
    assert calls[4][2]["fallback_context"] is fallback_context
    assert calls[4][2]["fallback_approve_url"] == "https://www.paypal.com/approve"
    assert calls[4][2]["fallback_ba_token"] == "BA-DEMO"
    assert calls[4][2]["signup_billing_payload"] is signup_billing_payload
    assert calls[4][2]["proxy_url"] == "socks5://proxy.example:1080"
    assert calls[4][2]["proxy_bypass"] == "localhost"
    assert calls[4][2]["fallback_use_camoufox"] is True
    assert calls[4][2]["fallback_use_roxybrowser"] is True
    assert calls[4][2]["roxybrowser_workspace_id"] == "workspace-1"
    assert calls[4][2]["roxybrowser_profile_id"] == "profile-1"


def test_handle_paypal_protocol_mode_dispatch_skips_browser_fallback_when_disabled():
    api = object()
    pre_extracted = None
    protocol_result = {"status": "needs_review", "paypal_approve_url": "https://www.paypal.com/approve"}
    calls = []

    result = payment_checkout_browser.handle_paypal_protocol_mode_dispatch(
        api,
        protocol_mode=True,
        pre_extracted=pre_extracted,
        email="user@example.com",
        checkout_url="https://pay.openai.com/c/pay/cs_demo",
        proxy_url=None,
        proxy_bypass=None,
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="",
        paypal_password="",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
        phone_accounts=[],
        timeout_seconds=120,
        is_cancelled=None,
        autofill_enabled=True,
        autofill_payload={},
        session_id="session-1",
        screenshot_paths=[],
        fallback_use_camoufox=False,
        fallback_use_roxybrowser=False,
        roxybrowser_workspace_id="",
        roxybrowser_profile_id="",
        handle_pre_extracted_checkout_without_ba=lambda value, **kwargs: calls.append(("pre", value, kwargs)) or None,
        build_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("build should not run")),
        prepare_auto_flow_payloads=lambda **_kwargs: (
            (_ for _ in ()).throw(AssertionError("disabled fallback must not prepare browser payloads"))
        ),
        handle_protocol_flow_dispatch=lambda **kwargs: (
            calls.append(("protocol", kwargs))
            or {"signup_billing_payload": {"country": "JP"}, "protocol_result": protocol_result}
        ),
        paypal_protocol_needs_browser_fallback=lambda value: calls.append(("needs_fallback", value)) or True,
        handle_protocol_browser_fallback_context=lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(AssertionError("disabled fallback must not build browser context"))
        ),
        handle_protocol_browser_fallback_dispatch=lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(AssertionError("disabled fallback must not run browser fallback"))
        ),
        browser_fallback_enabled=False,
    )

    assert result is protocol_result
    assert calls[-1] == ("needs_fallback", protocol_result)


def test_handle_paypal_protocol_mode_dispatch_hands_pre_extracted_ba_to_browser_fallback():
    api = object()
    pre_extracted = {"ba_token": "BA-DEMO"}
    calls = []

    result = payment_checkout_browser.handle_paypal_protocol_mode_dispatch(
        api,
        protocol_mode=True,
        pre_extracted=pre_extracted,
        email="user@example.com",
        checkout_url="",
        proxy_url=None,
        proxy_bypass=None,
        paypal_mode="create_account",
        paypal_country="JP",
        paypal_lang="ja",
        paypal_email="",
        paypal_password="",
        sms_url="https://sms.example.test",
        otp_channel="sms",
        paypal_card_number="",
        paypal_card_expiry="",
        paypal_card_cvv="",
        phone_accounts=[],
        timeout_seconds=120,
        is_cancelled=None,
        autofill_enabled=True,
        autofill_payload={},
        session_id="session-1",
        screenshot_paths=[],
        fallback_use_camoufox=True,
        fallback_use_roxybrowser=True,
        roxybrowser_workspace_id="workspace-1",
        roxybrowser_profile_id="profile-1",
        handle_pre_extracted_checkout_without_ba=lambda value, **kwargs: calls.append(("pre", value, kwargs)) or None,
        build_result=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("build should not run")),
        prepare_auto_flow_payloads=lambda **kwargs: (
            calls.append(("prepare", kwargs))
            or {"signup_billing_payload": {"country": "JP", "city": "Tokyo"}}
        ),
        handle_protocol_flow_dispatch=lambda **_kwargs: (
            (_ for _ in ()).throw(AssertionError("pre-extracted BA must not run protocol flow"))
        ),
        paypal_protocol_needs_browser_fallback=lambda value: calls.append(("needs_fallback", value)) or True,
        handle_protocol_browser_fallback_context=lambda result, **kwargs: (
            calls.append(("context", result, kwargs))
            or {
                "action": "fallback",
                "paypal_approve_url": result["paypal_approve_url"],
                "ba_token": result["ba_token"],
                "browser_entry_url": "https://www.paypal.com/signup?ba_token=BA-DEMO",
            }
        ),
        handle_protocol_browser_fallback_dispatch=lambda _api, **kwargs: (
            calls.append(("fallback", _api, kwargs)) or {"status": "needs_review", "via": "browser"}
        ),
    )

    assert result == {"status": "needs_review", "via": "browser"}
    assert calls[0][0] == "pre"
    assert calls[1][0] == "prepare"
    assert calls[2][0] == "context"
    assert calls[2][1]["paypal_approve_url"] == "https://www.paypal.com/agreements/approve?ba_token=BA-DEMO"
    assert calls[3][0] == "fallback"
    assert calls[3][1] is api
    fallback_kwargs = calls[3][2]
    assert fallback_kwargs["fallback_use_roxybrowser"] is True
    assert fallback_kwargs["roxybrowser_workspace_id"] == "workspace-1"
    assert fallback_kwargs["roxybrowser_profile_id"] == "profile-1"
    assert fallback_kwargs["fallback_ba_token"] == "BA-DEMO"
    assert fallback_kwargs["signup_billing_payload"] == {"country": "JP", "city": "Tokyo"}


def test_handle_paypal_signup_stop_before_otp_authorize_result_skips_without_flag():
    assert payment_checkout_browser.handle_paypal_signup_stop_before_otp_authorize_result({}) is None
    assert (
        payment_checkout_browser.handle_paypal_signup_stop_before_otp_authorize_result(
            {"_stop_before_signup_otp": False}
        )
        is None
    )


def test_handle_paypal_signup_stop_before_otp_authorize_result_returns_review_metadata():
    assert payment_checkout_browser.handle_paypal_signup_stop_before_otp_authorize_result(
        {"_stop_before_signup_otp": True}
    ) == {
        "action": "needs_review",
        "screenshot_label": "paypal-signup-before-otp",
        "failure_stage": "paypal_wait_signup_otp",
        "message": "PayPal 注册表单已提交，已按调试开关停在手机验证码输入前",
    }


def test_paypal_signup_stop_before_otp_result_fields_applies_defaults_and_overrides():
    assert payment_checkout_browser.paypal_signup_stop_before_otp_result_fields({}) == (
        "needs_review",
        "paypal-signup-before-otp",
        "paypal_wait_signup_otp",
        "PayPal 注册表单已提交，已按调试开关停在手机验证码输入前",
    )
    assert payment_checkout_browser.paypal_signup_stop_before_otp_result_fields(
        {
            "action": "failed",
            "screenshot_label": "custom-before-otp",
            "failure_stage": "custom_stage",
            "message": "custom message",
        }
    ) == ("failed", "custom-before-otp", "custom_stage", "custom message")


def test_handle_paypal_signup_flow_failure_authorize_result_skips_when_ok():
    assert (
        payment_checkout_browser.handle_paypal_signup_flow_failure_authorize_result(
            ok=True,
            error="ignored",
            otp_phone_lock_key="otp-lock",
            release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("release should not run")
            ),
        )
        is None
    )


def test_handle_paypal_signup_flow_failure_authorize_result_releases_lock_and_returns_failed_metadata():
    releases = []
    def on_progress(event):
        return None

    result = payment_checkout_browser.handle_paypal_signup_flow_failure_authorize_result(
        ok=False,
        error="signup failed",
        otp_phone_lock_key="otp-lock",
        release_otp_phone_lock=lambda key, **kwargs: releases.append((key, kwargs)),
        on_progress=on_progress,
    )

    assert result == {
        "action": "failed",
        "otp_phone_lock_key": "",
        "screenshot_label": "paypal-signup-failed",
        "failure_stage": "paypal_signup",
        "message": "signup failed",
    }
    assert releases == [("otp-lock", {"on_progress": on_progress})]


def test_handle_paypal_signup_flow_failure_authorize_result_returns_failed_metadata_without_lock():
    result = payment_checkout_browser.handle_paypal_signup_flow_failure_authorize_result(
        ok=False,
        error="signup failed",
        otp_phone_lock_key="",
        release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release should not run")
        ),
    )

    assert result == {
        "action": "failed",
        "otp_phone_lock_key": "",
        "screenshot_label": "paypal-signup-failed",
        "failure_stage": "paypal_signup",
        "message": "signup failed",
    }


def test_paypal_signup_flow_failure_result_fields_applies_defaults_and_overrides():
    assert payment_checkout_browser.paypal_signup_flow_failure_result_fields({}, fallback_error="signup failed") == (
        "",
        "failed",
        "paypal-signup-failed",
        "paypal_signup",
        "signup failed",
    )
    assert payment_checkout_browser.paypal_signup_flow_failure_result_fields(
        {
            "otp_phone_lock_key": "otp-lock",
            "action": "needs_review",
            "screenshot_label": "custom-signup",
            "failure_stage": "custom_stage",
            "message": "custom message",
        },
        fallback_error="signup failed",
    ) == ("otp-lock", "needs_review", "custom-signup", "custom_stage", "custom message")


def test_handle_paypal_signup_login_redirect_authorize_result_normalizes_continue_state():
    assert payment_checkout_browser.handle_paypal_signup_login_redirect_authorize_result(
        {
            "action": "continue",
            "signup_login_redirect_count": "2",
            "signup_email_submitted": 1,
            "signup_email_submitted_at": "12.5",
            "signup_form_submitted": "",
            "signup_submitted_at": None,
        }
    ) == {
        "action": "continue",
        "signup_login_redirect_count": 2,
        "signup_email_submitted": True,
        "signup_email_submitted_at": 12.5,
        "signup_form_submitted": False,
        "signup_submitted_at": 0.0,
    }


def test_handle_paypal_signup_login_redirect_authorize_result_normalizes_failed_metadata():
    assert payment_checkout_browser.handle_paypal_signup_login_redirect_authorize_result(
        {
            "action": "failed",
            "message": "still on login",
        }
    ) == {
        "action": "failed",
        "screenshot_label": "paypal-signup-login-page",
        "failure_stage": "paypal_signup",
        "message": "still on login",
    }
    assert payment_checkout_browser.handle_paypal_signup_login_redirect_authorize_result(
        {
            "action": "failed",
            "screenshot_label": "custom-login",
        }
    ) == {
        "action": "failed",
        "screenshot_label": "custom-login",
        "failure_stage": "paypal_signup",
        "message": "PayPal 仍停留在已有账号登录页，注册模式已停止提交登录表单",
    }


def test_handle_paypal_signup_login_redirect_authorize_result_skips_empty_or_unknown_action():
    assert payment_checkout_browser.handle_paypal_signup_login_redirect_authorize_result(None) is None
    assert payment_checkout_browser.handle_paypal_signup_login_redirect_authorize_result({}) is None
    assert payment_checkout_browser.handle_paypal_signup_login_redirect_authorize_result({"action": "noop"}) is None


def test_paypal_signup_login_redirect_continue_values_coerces_state_tuple():
    assert payment_checkout_browser.paypal_signup_login_redirect_continue_values(
        {
            "signup_login_redirect_count": "3",
            "signup_email_submitted": 1,
            "signup_email_submitted_at": "12.5",
            "signup_form_submitted": "",
            "signup_submitted_at": None,
        }
    ) == (3, True, 12.5, False, 0.0)


def test_paypal_signup_login_redirect_failed_result_fields_applies_defaults_and_overrides():
    assert payment_checkout_browser.paypal_signup_login_redirect_failed_result_fields({}) == (
        "failed",
        "paypal-signup-login-page",
        "paypal_signup",
        "PayPal 仍停留在已有账号登录页，注册模式已停止提交登录表单",
    )
    assert payment_checkout_browser.paypal_signup_login_redirect_failed_result_fields(
        {
            "action": "needs_review",
            "screenshot_label": "custom-login",
            "failure_stage": "custom_stage",
            "message": "custom message",
        }
    ) == ("needs_review", "custom-login", "custom_stage", "custom message")


def test_handle_paypal_signup_stuck_recover_authorize_result_normalizes_failed_metadata():
    assert payment_checkout_browser.handle_paypal_signup_stuck_recover_authorize_result(
        {
            "action": "failed",
            "message": "email timed out",
        }
    ) == {
        "action": "failed",
        "screenshot_label": "paypal-signup-email-timeout",
        "failure_stage": "paypal_signup",
        "message": "email timed out",
    }
    assert payment_checkout_browser.handle_paypal_signup_stuck_recover_authorize_result(
        {
            "action": "failed",
            "screenshot_label": "custom-timeout",
        }
    ) == {
        "action": "failed",
        "screenshot_label": "custom-timeout",
        "failure_stage": "paypal_signup",
        "message": "等待 PayPal 注册表单加载超时",
    }


def test_handle_paypal_signup_stuck_recover_authorize_result_normalizes_continue_state():
    assert payment_checkout_browser.handle_paypal_signup_stuck_recover_authorize_result(
        {
            "action": "continue",
            "signup_email_submitted": "",
            "signup_email_submitted_at": "12.5",
        }
    ) == {
        "action": "continue",
        "signup_email_submitted": False,
        "signup_email_submitted_at": 12.5,
    }


def test_paypal_signup_stuck_recover_failed_result_fields_applies_defaults_and_overrides():
    assert payment_checkout_browser.paypal_signup_stuck_recover_failed_result_fields({}) == (
        "failed",
        "paypal-signup-email-timeout",
        "paypal_signup",
        "等待 PayPal 注册表单加载超时",
    )
    assert payment_checkout_browser.paypal_signup_stuck_recover_failed_result_fields(
        {
            "action": "needs_review",
            "screenshot_label": "custom-timeout",
            "failure_stage": "custom_stage",
            "message": "custom message",
        }
    ) == ("needs_review", "custom-timeout", "custom_stage", "custom message")


def test_paypal_signup_stuck_recover_continue_values_coerces_state_tuple():
    assert payment_checkout_browser.paypal_signup_stuck_recover_continue_values(
        {
            "signup_email_submitted": 1,
            "signup_email_submitted_at": "12.5",
        }
    ) == (True, 12.5)


def test_handle_paypal_signup_stuck_recover_authorize_result_skips_empty_or_unknown_action():
    assert payment_checkout_browser.handle_paypal_signup_stuck_recover_authorize_result(None) is None
    assert payment_checkout_browser.handle_paypal_signup_stuck_recover_authorize_result({}) is None
    assert payment_checkout_browser.handle_paypal_signup_stuck_recover_authorize_result({"action": "noop"}) is None


def test_handle_paypal_login_step_failure_authorize_result_skips_when_ok():
    assert payment_checkout_browser.handle_paypal_login_step_failure_authorize_result(ok=True, error="ignored") is None


def test_handle_paypal_login_step_failure_authorize_result_returns_failed_metadata():
    assert payment_checkout_browser.handle_paypal_login_step_failure_authorize_result(
        ok=False,
        error="missing password",
    ) == {
        "action": "failed",
        "screenshot_label": "paypal-login-failed",
        "failure_stage": "paypal_login",
        "message": "missing password",
    }


def test_paypal_login_step_failure_result_fields_applies_defaults_and_overrides():
    assert payment_checkout_browser.paypal_login_step_failure_result_fields(
        {},
        fallback_error="missing password",
    ) == ("failed", "paypal-login-failed", "paypal_login", "missing password")
    assert payment_checkout_browser.paypal_login_step_failure_result_fields(
        {
            "action": "needs_review",
            "screenshot_label": "custom-login",
            "failure_stage": "custom_stage",
            "message": "custom message",
        },
        fallback_error="missing password",
    ) == ("needs_review", "custom-login", "custom_stage", "custom message")


def test_handle_paypal_authorize_timeout_releases_lock_and_returns_review_metadata():
    releases = []
    def on_progress(event):
        return None

    result = payment_checkout_browser.handle_paypal_authorize_timeout(
        otp_phone_lock_key="otp-lock",
        release_otp_phone_lock=lambda key, **kwargs: releases.append((key, kwargs)),
        on_progress=on_progress,
    )

    assert result == {
        "action": "needs_review",
        "otp_phone_lock_key": "",
        "screenshot_label": "paypal-authorize-timeout",
        "failure_stage": "paypal_authorize",
        "message": "等待 PayPal 登录/授权超时，需要人工确认",
    }
    assert releases == [("otp-lock", {"on_progress": on_progress})]


def test_handle_paypal_authorize_timeout_returns_review_metadata_without_lock():
    assert payment_checkout_browser.handle_paypal_authorize_timeout(
        otp_phone_lock_key="",
        release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("release should not run")
        ),
    ) == {
        "action": "needs_review",
        "otp_phone_lock_key": "",
        "screenshot_label": "paypal-authorize-timeout",
        "failure_stage": "paypal_authorize",
        "message": "等待 PayPal 登录/授权超时，需要人工确认",
    }


def test_paypal_authorize_timeout_result_fields_applies_defaults_and_overrides():
    assert payment_checkout_browser.paypal_authorize_timeout_result_fields({}) == (
        "",
        "needs_review",
        "paypal-authorize-timeout",
        "paypal_authorize",
        "等待 PayPal 登录/授权超时，需要人工确认",
    )
    assert payment_checkout_browser.paypal_authorize_timeout_result_fields(
        {
            "otp_phone_lock_key": "otp-lock",
            "action": "failed",
            "screenshot_label": "custom-timeout",
            "failure_stage": "custom_stage",
            "message": "custom message",
        }
    ) == ("otp-lock", "failed", "custom-timeout", "custom_stage", "custom message")


def test_handle_paypal_signup_visible_state_wait_skips_when_no_visible_signup_state():
    assert (
        payment_checkout_browser.handle_paypal_signup_visible_state_wait(
            {},
            sleep_seconds=1.5,
            sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run")),
        )
        is None
    )


def test_handle_paypal_signup_visible_state_wait_sleeps_for_email_locator_or_registration_ready():
    for state in [{"email_locator": object()}, {"registration_ready": True}]:
        sleeps = []

        assert payment_checkout_browser.handle_paypal_signup_visible_state_wait(
            state,
            sleep_seconds=1.5,
            sleep=sleeps.append,
        ) == {"action": "continue"}
        assert sleeps == [1.5]


def test_handle_paypal_authorize_idle_wait_sleeps_and_continues():
    sleeps = []

    assert payment_checkout_browser.handle_paypal_authorize_idle_wait(
        sleep_seconds=1.0,
        sleep=sleeps.append,
    ) == {"action": "continue"}
    assert sleeps == [1.0]


def test_handle_paypal_approve_ready_skips_when_not_ready_or_click_fails():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutnow?token=demo"))

    assert (
        payment_checkout_browser.handle_paypal_approve_ready(
            api,
            state={},
            otp_phone_lock_key="otp-lock",
            click_approve=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("click should not run")),
            release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("release should not run")
            ),
            wait_for_return=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
        )
        is None
    )
    assert (
        payment_checkout_browser.handle_paypal_approve_ready(
            api,
            state={"approve_ready": True},
            otp_phone_lock_key="otp-lock",
            click_approve=lambda *_args, **_kwargs: False,
            release_otp_phone_lock=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("release should not run")
            ),
            wait_for_return=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wait should not run")),
        )
        is None
    )


def test_handle_paypal_approve_ready_releases_otp_lock_and_waits_for_return():
    api = FakeApi(FakePage(url="https://www.paypal.com/checkoutnow?token=demo"))
    progress_events = []
    on_progress = progress_events.append
    calls = []

    result = payment_checkout_browser.handle_paypal_approve_ready(
        api,
        state={"approve_ready": True},
        otp_phone_lock_key="otp-lock",
        click_approve=lambda target, **kwargs: calls.append(("click", target, kwargs)) or True,
        release_otp_phone_lock=lambda key, **kwargs: calls.append(("release", key, kwargs)),
        wait_for_return=lambda target, **kwargs: calls.append(("wait", target, kwargs)) or {"status": "success"},
        on_progress=on_progress,
    )

    assert result == {
        "action": "return",
        "otp_phone_lock_key": "",
        "result": {"status": "success"},
    }
    assert calls == [
        ("click", api, {"on_progress": on_progress}),
        ("release", "otp-lock", {"on_progress": on_progress}),
        ("wait", api, {"on_progress": on_progress}),
    ]


def test_paypal_approve_return_values_returns_lock_key_and_result_by_reference():
    paypal_result = {"status": "success", "message": "approved"}

    assert payment_checkout_browser.paypal_approve_return_values({"result": paypal_result}) == ("", paypal_result)
    assert payment_checkout_browser.paypal_approve_return_values(
        {"otp_phone_lock_key": "otp-lock", "result": paypal_result}
    ) == ("otp-lock", paypal_result)


def test_wait_for_paypal_subscription_return_confirms_loaded_return_page():
    api = FakeApi(FakePage(url="https://pay.openai.com/c/pay/cs_live_return"))
    progress_events = []
    screenshots = []
    sync_calls = []
    sleeps = []
    times = iter([0, 0, 0])

    result = payment_checkout_browser.wait_for_paypal_subscription_return(
        api,
        session_id="demo",
        screenshot_paths=[],
        timeout_seconds=120,
        settle_seconds=1.0,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        on_progress=progress_events.append,
        capture_screenshot=lambda _api, session_id, stage, paths: screenshots.append((session_id, stage, paths)),
        build_result=lambda status, **extra: {"status": status, **extra},
        sync_relevant_payment_page=lambda _api, **kwargs: sync_calls.append(kwargs),
        is_return_url=lambda url: "openai.com" in url,
        is_paypal_host=lambda _url: False,
        classify_paypal_checkout_state=lambda _url, _body: None,
        body_excerpt=lambda _api: "",
        time_fn=lambda: next(times),
        sleep=sleeps.append,
    )

    assert result == {
        "status": "success",
        "failure_stage": "",
        "message": "PayPal 授权后已回跳 ChatGPT/OpenAI 页面，确认绑定成功",
        "screenshot_paths": [],
    }
    assert api.page.loaded == [("load", 10000)]
    assert sync_calls == [{"prefer_paypal": False}]
    assert screenshots == [("demo", "success", [])]
    assert sleeps == [1.0]
    assert [event["stage"] for event in progress_events] == ["paypal_return_wait", "paypal_return_confirmed"]


def test_wait_for_paypal_subscription_return_uses_paypal_failure_classification():
    api = FakeApi(FakePage(url="https://www.paypal.com/agreements/approve?ba_token=BA-123", body="risk"))
    screenshots = []
    times = iter([0, 0])

    result = payment_checkout_browser.wait_for_paypal_subscription_return(
        api,
        session_id="demo",
        screenshot_paths=["before.png"],
        timeout_seconds=120,
        settle_seconds=1.0,
        progress_event=lambda stage, **extra: {"stage": stage, **extra},
        capture_screenshot=lambda _api, session_id, stage, paths: screenshots.append((session_id, stage, list(paths))),
        build_result=lambda status, **extra: {"status": status, **extra},
        sync_relevant_payment_page=lambda _api, **_kwargs: None,
        is_return_url=lambda _url: False,
        is_paypal_host=lambda url: "paypal.com" in url,
        classify_paypal_checkout_state=lambda _url, body: {
            "status": "failed",
            "failure_stage": "paypal_risk",
            "message": body,
        },
        body_excerpt=lambda api: api.page.body,
        time_fn=lambda: next(times),
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("sleep should not run after classification")),
    )

    assert result == {
        "status": "failed",
        "failure_stage": "paypal_risk",
        "message": "risk",
        "screenshot_paths": ["before.png"],
    }
    assert screenshots == [("demo", "paypal-authorize-failed", ["before.png"])]


def test_accept_checkout_terms_checks_visible_unchecked_boxes():
    class FakeCheckbox:
        def __init__(self):
            self.checked = False

        def is_visible(self, timeout=None):
            return True

        def is_disabled(self, timeout=None):
            return False

        def is_checked(self, timeout=None):
            return self.checked

        def scroll_into_view_if_needed(self, timeout=None):
            return None

        def check(self, timeout=None, force=False):
            self.checked = True

    class FakeLocatorCollection:
        def __init__(self, items):
            self.items = items

        def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class FakeFrame:
        def __init__(self, boxes):
            self.boxes = boxes

        def locator(self, selector):
            return FakeLocatorCollection(self.boxes)

    checkbox = FakeCheckbox()
    progress = []

    count = payment_checkout_browser.accept_checkout_terms_on_page(
        object(),
        progress=lambda stage, **extra: progress.append((stage, extra)),
        frames=lambda api: [FakeFrame([checkbox])],
        sleep=lambda seconds: None,
    )

    assert count == 1
    assert progress == [("accept_checkout_terms", {}), ("checkout_terms_accepted", {"count": 1})]


def test_select_chatgpt_account_clicks_matching_account():
    page = FakePage(evaluate_result={"clicked": True, "text": "Continue user@example.com"})
    api = FakeApi(page)

    selected = payment_checkout_browser.select_chatgpt_account_if_needed(
        api,
        email="USER@example.com",
        body_excerpt=lambda api, limit: "Choose an account user@example.com",
        sleep=lambda seconds: None,
    )

    assert selected is True
    assert page.evaluated[0][1] == ("user@example.com",)
    assert page.loaded == [("domcontentloaded", 15000)]
    assert page.waited == [2500]


def test_open_checkout_in_page_succeeds_after_goto_sets_checkout_url():
    checkout_url = "https://chatgpt.com/checkout/openai_llc/cs_test_123"
    api = FakeApi(FakePage())
    goto_calls = []

    def fake_goto(page, url, **kwargs):
        goto_calls.append((page, url, kwargs))
        page.url = checkout_url
        return True

    result = payment_checkout_browser.open_checkout_in_page(
        api,
        checkout_url,
        email="user@example.com",
        goto=fake_goto,
        is_checkout=lambda api: False,
        body_excerpt=lambda api, limit: "",
        extract_checkout_session_id=lambda url: "cs_test_123",
        select_account=lambda api, email: False,
        sleep=lambda seconds: None,
        timeout_seconds=0.1,
    )

    assert result is True
    assert goto_calls[0][1] == checkout_url


def test_open_checkout_in_page_uses_new_page_after_initial_goto_failure():
    checkout_url = "https://chatgpt.com/checkout/openai_llc/cs_test_123"
    api = FakeApi(FakePage())
    attempts = []

    def fake_goto(page, url, **kwargs):
        attempts.append(page)
        if len(attempts) == 1:
            raise RuntimeError("closed")
        page.url = checkout_url
        return True

    result = payment_checkout_browser.open_checkout_in_page(
        api,
        checkout_url,
        goto=fake_goto,
        is_checkout=lambda api: False,
        body_excerpt=lambda api, limit: "",
        extract_checkout_session_id=lambda url: "cs_test_123",
        select_account=lambda api, email: False,
        sleep=lambda seconds: None,
        timeout_seconds=0.1,
    )

    assert result is True
    assert api.page is api.context.pages[0]
