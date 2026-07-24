# PayPal 真 BA 提链调查 — 2026-07-24

## 问题定位

`src/autotoken/payments/us_paypal.py::generate_paypal_trial()` 在 Stripe init 后优先调用：

```text
POST https://api.stripe.com/v1/elements/express_billing_agreement
```

该 Express BA endpoint 只需要 Stripe public key / paypal sdk version，不携带当前 `checkout_session_id (cs_*)`，因此能返回外观合法的 `https://www.paypal.com/agreements/approve?ba_token=BA-*`，但不能证明该 BA 绑定到 ChatGPT/OpenAI 的账单 checkout session。

本地 `data/us_paypal_links.json` 现有记录特征与该问题一致：每条都有 `cs_live_*`，但 `paypal_link/provider_redirect_url` 为直接 PayPal BA，且旧记录未保存 `link_source/link_binding`，无法证明来自当前 `payment_pages/{cs_id}/confirm` 或 approve poll。

## 真链接验收标准

接受链路必须满足：

1. `checkout` 先拿到 `checkout_session_id=cs_*` 和 `processor_entity`。
2. Stripe init / promo / tax 后确认金额为 0 且 payment methods 包含 PayPal。
3. PayPal redirect/BA 只能来自当前 checkout session 相关路径：
   - `POST /v1/payment_pages/{cs_id}/confirm`；或
   - `POST chatgpt.com/backend-api/payments/checkout/approve` 后 `GET /v1/payment_pages/{cs_id}` 轮询出的 redirect。
4. 如果只拿到 `pm-redirects.stripe.com/authorize/*`，必须跟随 30x/响应体解析成 `paypal.com/agreements/approve?ba_token=BA-*` 后才算成功。
5. 独立 Express BA 标记为 `link_binding=unbound_express`，不能作为 ChatGPT/OpenAI 账单 BA 入库。

## 代码处理

- 移除 `generate_paypal_trial()` 中 Express BA 的成功短路。
- 新增 `finalize_bound_paypal_result()`：统一解析 PayPal BA，并写入：
  - `link_source=stripe_payment_pages_confirm` 或 `stripe_checkout_approve_poll`
  - `link_binding=chatgpt_checkout_session`
- `create_express_billing_agreement()` 保留为诊断 helper，但返回 `link_binding=unbound_express`。
- `/api/us-paypal` 入库记录新增 `link_source` / `link_binding` 字段，便于 UI/数据层区分真假来源。

## 验证

```bash
uv run ruff check src/autotoken/payments/us_paypal.py src/autotoken/api_routes/us_paypal.py tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py
uv run pytest tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py tests/unit/test_paypal_protocol_local_service.py -q
```

结果：`All checks passed`，`39 passed`。

## 后续 live 测试建议

美国 PP 优先跑单账号、小并发，观察日志中是否出现：

```text
[5/6] inline confirm PayPal（只接受绑定当前 checkout session 的 BA redirect）
confirm submission=... redirect=True
```

或：

```text
[6/6] approve + poll PayPal
poll */19 ... success=True
```

成功入库记录应包含：

```json
{
  "link_source": "stripe_payment_pages_confirm | stripe_checkout_approve_poll",
  "link_binding": "chatgpt_checkout_session",
  "cs_id": "cs_*",
  "paypal_link": "https://www.paypal.com/agreements/approve?ba_token=BA-*"
}
```
