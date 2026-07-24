# PayPal 真 BA 提链修复报告 — 2026-07-24

## 结论

已确认旧实现优先返回 Stripe Express Billing Agreement 链接；该链接未绑定当前 OpenAI/ChatGPT checkout session，属于“外观合法但账单不绑定”的假 BA。已改为只接受来自当前 `cs_*` 的 Stripe Payment Page confirm / ChatGPT approve poll redirect。

## 变更文件

- `/Users/mac/code/my/AutoTeam-F/src/autotoken/payments/us_paypal.py`
- `/Users/mac/code/my/AutoTeam-F/src/autotoken/api_routes/us_paypal.py`
- `/Users/mac/code/my/AutoTeam-F/tests/unit/test_us_paypal_payment.py`
- `/Users/mac/code/my/AutoTeam-F/tests/unit/test_us_paypal_routes.py`

## 验收命令与结果

```text
uv run ruff check ... -> All checks passed
uv run pytest tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py tests/unit/test_paypal_protocol_local_service.py -q -> 39 passed
```

全量 `uv run pytest -q` 当前仍有 17 个既有无关失败，集中在旧 route default、CLI mock、OAuth live fallback、rename/build artifact 约束，不是本次 PayPal 提链改动引入；PayPal 相关目标测试全绿。
