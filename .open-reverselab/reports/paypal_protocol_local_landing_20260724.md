# PayPal US 本地协议支付落地记录（2026-07-24）

## 结论

已将 `/Users/mac/Downloads/openai-paypal-main` 中验证成功的 US no-FI 协议支付链路落入 AutoTeam-F：

- 后端使用仓库内置本地协议引擎：`/Users/mac/code/my/AutoTeam-F/src/autotoken/_paypal_protocol_engine/`
- API 入口：`POST /api/us-paypal/protocol/start`
- 状态轮询：`GET /api/us-paypal/protocol/jobs/{job_id}`
- 取消：`POST /api/us-paypal/protocol/jobs/{job_id}/cancel`
- 前端：`/Users/mac/code/my/AutoTeam-F/web/src/components/UsPaypalPage.vue` 顶部 tab 切换 `PayPal 提链` / `协议支付`

## 固化的已验证参数

本地 runner 强制使用此前成功的组合：

```text
PAYPAL_USE_CURL_CFFI=0
PAYPAL_HEADLESS_USE_PINNED_FINGERPRINT=1
PAYPAL_HEADLESS_PINNED_FINGERPRINT_PATH=src/autotoken/_paypal_protocol_engine/var/roxy_ios_fingerprint_current.json
PAYPAL_RISK_SIGNALS_MODE=headless
PAYPAL_RISK_HEADLESS_WAIT_SECONDS=45
PAYPAL_DATADOME_MODE=headless
PAYPAL_MTR_RUNTIME=headless
PAYPAL_APPROVAL_PATH=create_member_no_fi
--approval-path create-member-no-fi
--fingerprint-source headless
--datadome-mode headless
--mtr-runtime headless
--risk-signals-mode headless
```

## 安全/脱敏边界

- 不调用第三方远程兼容网站。
- 日志输出会脱敏：BA token、SMS record token、proxy userinfo、常见 secret/cookie/password/access_token 字段。
- 未写入真实 BA、真实代理、真实 SMS token。

## 验证

```bash
.venv/bin/python -m py_compile src/autotoken/_paypal_protocol_engine/main.py src/autotoken/_paypal_protocol_engine/config.py src/autotoken/_paypal_protocol_engine/paypal/*.py src/autotoken/api_routes/us_paypal.py src/autotoken/payments/us_paypal.py src/autotoken/services/paypal_protocol_local.py
.venv/bin/pytest tests/unit/test_us_paypal_payment.py tests/unit/test_us_paypal_routes.py tests/unit/test_paypal_protocol_local_service.py -q
cd web && npm run build
.venv/bin/python src/autotoken/_paypal_protocol_engine/main.py --help
```

结果：

```text
30 passed
vite build success
engine --help success
```
