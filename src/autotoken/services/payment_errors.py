"""Shared payment-flow exception types."""

from __future__ import annotations


class PaymentFlowError(RuntimeError):
    def __init__(self, message: str, stage: str = "payment_http"):
        super().__init__(message)
        self.stage = stage


class PaymentOTPCancelled(PaymentFlowError):
    pass
