import json

from autotoken.services import payment_checkout_browser, payment_form_fields

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
