def test_random_birthday_default_year_is_before_2000(monkeypatch):
    from autotoken.core import identity

    calls = []

    def fake_randint(start, end):
        calls.append((start, end))
        return start if len(calls) == 1 else 1

    monkeypatch.setattr(identity.random, "randint", fake_randint)

    birthday = identity.random_birthday()

    assert int(birthday["year"]) <= 1999

