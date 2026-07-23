# PayPal 本地链路继续调查 — 2026-07-24 01:05 CST

## 本轮范围

- 读取 open-reverselab 全局与 Web 板块 AI 使用规范。
- 复查 `/Users/mac/Downloads/openai-paypal-main` 的核心链路代码与既有研究产物。
- 未修改 `/Users/mac/code/my/AutoTeam-F` 业务代码。
- 未使用真实代理、SMS token、BA token 做 live 自动注册/支付重放。

## 本地验证

```bash
/Users/mac/Downloads/openai-paypal-main/.venv/bin/python -m py_compile \
  /Users/mac/Downloads/openai-paypal-main/paypal/*.py \
  /Users/mac/Downloads/openai-paypal-main/main.py \
  /Users/mac/Downloads/openai-paypal-main/web.py

/Users/mac/Downloads/openai-paypal-main/.venv/bin/python \
  /Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro/test_downloads_integrated_create_member_no_fi_v8.py
```

结果：`py_compile` 通过；v8 no-FI mock 集成验收通过，`phase4_status=success`，`phase4_state=APPROVED`。

## openai-paypal-main 中的必要信息确认

核心路径仍在：

- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:5776`：US auto 默认启用 `create_member_no_fi`。
- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:5789`：构造 `CreateMemberAccountMutation` no-card/no-bank 变量。
- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:5815`：执行 `CreateMemberAccountMutation` 并保存 `buyer.userId` / EUAT。
- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:7769`：执行 `ApproveMemberPaymentMutation(primaryFundingOptionId=null)`。
- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:7940`：Phase4 优先走 no-primary-FI approve。

既有成功证据仍指向：

```text
Fresh BA -> EC/signup context -> OTP confirm -> CreateMemberAccount(no FI) -> ApproveMemberPayment(primaryFundingOptionId=null) -> APPROVED + returnUrl
```

证据文件：

- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/live_v8/live_create_member_no_fi_v8_rerun_20260723_234919.json`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/live_v8/live_create_member_no_fi_v8_rerun_20260723_234919.log`

## 当前不稳定点

后续 fresh run 的 `CreateMemberAccount` 前置 browser-risk 不完整：

```text
signup-context HTTP 403 DataDome challenge
observed=observability
missing=fraudnet_p1,fraudnet_p2,fraudnet_w,identity_di_log,tealeaf,datadog_rum
CreateMemberAccountMutation -> OAS_ERROR
```

诊断文件：

- `/Users/mac/Downloads/openai-paypal-main/var/headless_last_missing_signup_context.json`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/live_v8/headless_signup_context_missing_summary_20260724_0056.json`

## 工程结论

`openai-paypal-main` 已包含本地 US no-FI PayPal approve 协议链的关键实现和 mock 验收。当前 live 不稳定不是缺少 GraphQL shape，而是 PayPal 风控/浏览器上下文 gating。该类 gating 不是应该固化到云端生产服务的依赖点。

可落地的生产方向应切到官方 PayPal Checkout / Subscriptions / Vault API：前端 JS SDK 引导买家授权，后端使用 merchant REST credentials 创建 order/subscription/setup token，并通过 webhook/查询接口确认状态。
