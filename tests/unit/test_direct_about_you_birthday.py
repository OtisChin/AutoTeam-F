from autotoken.interfaces import manager


def test_about_you_birthday_text_value_uses_day_month_year_before_2000():
    value = manager._about_you_birthday_text_value({"year": "1994", "month": "08", "day": "17"})

    assert value == "17/08/1994"
    assert not value.endswith("2026")


def test_about_you_birthday_selectors_include_single_birthday_input():
    selectors = manager._ABOUT_YOU_BIRTHDAY_TEXT_SELECTORS

    assert "Birthday" in selectors
    assert "birth" in selectors.lower()
