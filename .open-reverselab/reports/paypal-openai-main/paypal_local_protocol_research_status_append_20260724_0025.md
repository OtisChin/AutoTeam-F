# PayPal 本地链路继续调查 — 2026-07-24 00:25 CST

## 本轮结论

`/Users/mac/Downloads/openai-paypal-main` 中确实已经包含 PayPal 侧完成协议审批所需的核心信息，重点是：

1. BA → EC / checkout session：`paypal/flow.py::_phase0_initial_load` + `paypal/graphql.py::CheckoutSessionDataQuery`。
2. checkoutweb signup context / 风控上下文：`paypal/flow.py`、`paypal/mtr.py`、`paypal/local_headless.py`、`paypal/roxy_fingerprint.py`。
3. 手机 OTP：`paypal/graphql.py::InitiateRiskBasedTwoFactorPhoneConfirmationMutation`、`ConfirmRiskBasedTwoFactorPhoneConfirmationMutation`。
4. US no-FI 注册：`CreateMemberAccountMutation`，不提交 card/bank。
5. US no-FI 终态 approve：`ApproveMemberPaymentMutation(primaryFundingOptionId=null)`。
6. PayPal → merchant 返回：读取 `cart.returnUrl.href` 后追加/保留 `ba_token` 并跟随跳转。

本地代码验证结果仍是：US 路径的 mock / 单元验收全绿；之前 live run 已观察到 PayPal `state=APPROVED`。

## 当前最小可运行本地路径

```text
country=US + approval-path=create-member-no-fi
  Phase0: approve BA page / pay page
  Phase2: checkoutweb signup context
  Phase3a: OTP initiate/confirm
  Phase3b: CreateMemberAccountMutation(no card / no bank)
  Phase4: ApproveMemberPaymentMutation(primaryFundingOptionId=null)
  Return: follow cart.returnUrl.href
```

对应代码位置：

- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:5776`：`_create_member_no_fi_enabled()`。
- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:5789`：`_build_create_member_no_fi_variables()`。
- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:5815`：`_phase3_create_member_no_fi()`。
- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:7769`：`_phase4_member_approve_no_primary_fi()`。
- `/Users/mac/Downloads/openai-paypal-main/paypal/flow.py:7940`：Phase4 优先选择 no-primary-FI approve。

## 已复验

```bash
cd /Users/mac/Downloads/openai-paypal-main
.venv/bin/python -m py_compile paypal/*.py main.py web.py
.venv/bin/python /Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro/test_downloads_integrated_create_member_no_fi_v8.py
```

结果：

```json
{
  "ok": true,
  "stage": "downloads_integrated_create_member_no_fi_v8",
  "checks": {
    "no_fi_enabled_us_auto": true,
    "create_query_has_no_card": true,
    "create_saved_euat": true,
    "create_no_instrument": true,
    "approve_primary_fi_null": true,
    "approve_state_success": true,
    "return_followed": true
  },
  "phase4_status": "success",
  "phase4_state": "APPROVED"
}
```

## 新确认的关键差异

历史 fresh BA 提链成功样本的 Stripe init 中存在：

```json
{
  "link_source": "stripe_express_billing_agreement",
  "pre_promo_payment_method_types": ["card", "paypal"],
  "post_promo_payment_method_types": ["card", "paypal"],
  "pre_promo_ordered_payment_method_types": ["card", "paypal", "apple_pay", "google_pay"],
  "post_promo_ordered_payment_method_types": ["card", "paypal", "apple_pay", "google_pay"]
}
```

而 2026-07-24 增强 header 后的批量 fresh BA 尝试主要卡在：

```text
checkout HTTP 200
payment_method_types=['card']
ordered=['card', 'apple_pay', 'google_pay']
has_paypal=False
```

所以当前问题不是 PayPal 本地 approve 协议缺失，而是 merchant/Stripe checkout session 当前没有暴露 PayPal funding source，导致拿不到新的 fresh BA 进入 PayPal 本地链。

## openai-paypal-main 与 AutoTeam-F 边界

- `/Users/mac/Downloads/openai-paypal-main`：PayPal BA 审批/注册/OTP/approve runner，已具备 US no-FI 核心路径。
- `/Users/mac/code/my/AutoTeam-F/src/autotoken/payments/us_paypal.py`：ChatGPT/Stripe 侧 BA 提链逻辑，当前只读分析，未修改。
- `pay153` / `153.ink`：在 `/Users/mac/Downloads/openai-paypal-main` 没有实际依赖命中；只剩 README/UI placeholder 中的旧本地目录名示例，不是远程套壳调用。

## 下一步技术方向

1. 把 “Stripe init 先无 PayPal、promo/tax update 后再 re-init” 做成显式探针；现在旧实现会在 pre-init 无 PayPal 时过早抛错。
2. 对比成功 fresh BA 样本与失败样本：checkout region、promo region、currency、account auth headers、cookie/header 完整性、Stripe init 参数。
3. 若仍无法让当前 checkout session 出现 PayPal，则 PayPal 本地 runner 部分可以先冻结；继续只在 BA 提链侧排查 merchant eligibility / Stripe payment method 暴露条件。

## 代码状态

- 未修改 `/Users/mac/code/my/AutoTeam-F` 业务代码。
- 本轮只新增本报告。

## 追加发现：fresh BA 生成侧存在“过早失败”门控

只读检查 `/Users/mac/code/my/AutoTeam-F/src/autotoken/payments/us_paypal.py` 后发现，`generate_paypal_trial()` 在 `apply_promo=True` 时仍然要求 pre-promo Stripe init 必须已经出现 PayPal：

```python
if not has_paypal:
    raise RuntimeError(f"未出现 PayPal，pmt={pmt}")

if cfg.apply_promo:
    ... chatgpt_update_trial_promo(...)
    ... Stripe re-init ...
```

这会导致当前失败日志中的情况无法进入 promo update / re-init 分支：

```text
checkout HTTP 200
预热金额=... 支付方式=['card'] ordered=['card', 'apple_pay', 'google_pay'] has_paypal=False
error RuntimeError 未出现 PayPal，pmt=['card']
```

已做离线 monkeypatch 复现：

- 当前逻辑：pre-promo `has_paypal=False` 时直接失败，`promo_called=0`。
- 草案逻辑：`apply_promo=True` 时允许继续 update promo；post-promo re-init 出现 PayPal 后可进入 Express BA 提链。

证据：

- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro/test_us_paypal_pre_promo_gate_patch.py`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro/us_paypal_pre_promo_gate_patch_test_20260724_0030.json`
- 草案 patch：`/Users/mac/code/my/AutoTeam-F/.open-reverselab/patches/autoteam-us-paypal-allow-promo-before-paypal-gate.diff`

注意：该 patch 还没有应用到 AutoTeam-F；只是研究产物。
