from pathlib import Path


PAYMENT_FILES = [
    Path("src/autotoken/payments/us_paypal.py"),
    Path("src/autotoken/payments/brazil_pix.py"),
    Path("src/autotoken/payments/india_upi.py"),
    Path("src/autotoken/payments/kakao_pay.py"),
    Path("src/autotoken/payments/momo_vn.py"),
]


def test_payment_approval_poll_attempts_are_limited_to_ten():
    for path in PAYMENT_FILES:
        source = path.read_text(encoding="utf-8")

        assert "range(1, 11)" in source, f"{path} should poll exactly 10 attempts"
        assert "poll {i}/10" in source, f"{path} should log poll denominator as 10"
        assert "range(1, 16)" not in source, f"{path} should not poll 15 attempts"
        assert "range(1, 20)" not in source, f"{path} should not poll 19 attempts"
        assert "poll {i}/15" not in source, f"{path} should not log 15 attempts"
        assert "poll {i}/19" not in source, f"{path} should not log 19 attempts"
