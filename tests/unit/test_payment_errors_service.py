from autotoken import gopay_executor
from autotoken.services import payment_errors


def test_payment_flow_error_carries_stage():
    exc = payment_errors.PaymentFlowError("failed", stage="checkout")

    assert str(exc) == "failed"
    assert exc.stage == "checkout"


def test_gopay_error_names_are_compatibility_aliases():
    assert gopay_executor.GoPayFlowError is payment_errors.PaymentFlowError
    assert gopay_executor.GoPayOTPCancelled is payment_errors.PaymentOTPCancelled

    exc = gopay_executor.GoPayOTPCancelled("cancelled", stage="fetch_otp")
    assert isinstance(exc, gopay_executor.GoPayFlowError)
    assert exc.stage == "fetch_otp"
