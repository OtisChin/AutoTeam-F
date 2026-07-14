from pathlib import Path

PAYPAL_PAGE = Path(__file__).resolve().parents[2] / "web" / "src" / "components" / "PayPalPage.vue"


def test_paypal_frontend_exposes_br_ba_mode_and_country():
    source = PAYPAL_PAGE.read_text(encoding="utf-8")

    assert '<option value="br">BR 模式（BR/BRL/custom）</option>' in source
    assert "['eu', 'us', 'br', 'gb'].includes" in source
    assert "['US', 'AU', 'BR', 'JP'].includes" in source
    assert "form.value.paypalBaMode === 'br'" in source
    assert "form.value.paypalBaPaymentMethodCountry = 'BR'" in source


def test_paypal_frontend_exposes_gb_ba_mode_and_forces_jp_payment_country():
    source = PAYPAL_PAGE.read_text(encoding="utf-8")

    assert '<option value="gb">GB 模式（GB/GBP/custom，JP 支付侧）</option>' in source
    assert "['eu', 'us', 'br', 'gb'].includes" in source
    assert "['US', 'AU', 'BR', 'JP'].includes" in source
    assert "form.value.paypalBaMode === 'gb'" in source
    assert "form.value.paypalBaPaymentMethodCountry = 'JP'" in source
