# PayPal 本地协议支付链路研究状态（2026-07-23）

## 当前结论

`/Users/mac/Downloads/openai-paypal-main` 里确实包含 PayPal 本地协议链路的大部分必要信息，但它的 Phase 4 仍是旧 `billing.authorize` 分支；当前 PayPal Weasley 前端的真实 post-onboarding 分支是：

1. `SignUpNewMemberMutation` / `onboardGuest`
2. 保存 `fundingOptions[0].fundingInstrument.id`（BILLING_WITHOUT_PURCHASE）
3. `ApproveOnboardPaymentMutation`
   - `attemptSetStickyFi(token, instrumentId)`
   - `approveGuestSignUpPayment(token)`
4. 取 `cart.returnUrl.href` 回跳商户

`openai-paypal-main` 已具备：
- BA approve 初始页解析、EC token 提取
- checkoutweb GraphQL 会话封装
- DataDome / MTR / risk signal 运行时
- signup + OTP 链路
- 本地 Web UI / CLI
- 代理和脱敏日志

缺口：
- US country/profile/schema 需要 patch
- signup 成功后的 `fundingInstrument.id` 没有被保存
- Phase 4 没有优先走 Weasley `ApproveOnboardPaymentMutation`
- existing-buyer 分支缺少合法 PayPal buyer auth state 和钱包 FI id

## 已本地验证（非 live 资金链）

- v5 mock acceptance 已重跑通过：
  `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro/acceptance_v5_rerun_20260723_230046.jsonl`
- 官方 PayPal REST mock E2E 已重跑通过：
  `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro/official_mock_rerun_20260723_230046.json`
- runtime cache 未发现成功支付/COMPLETED 的真实本地痕迹：
  `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/local_runtime_success_signals_20260723.json`

## 旧 BA 状态

用户给的 8 条 BA 已全部是 stale/invalid：均可导出 EC，但 checkout session 进入 generic error，GraphQL 返回 `INVALID_RESOURCE_ID` / `ALLOWED_CARD_TYPES_COULD_NOT_BE_RETRIEVED`。

证据：
`/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/ba_status_recheck_us_proxy_20260723.jsonl`

## Fresh BA 来源

`AutoTeam-F/src/autotoken/payments/us_paypal.py` 里已经有独立 BA 提链逻辑：

- ChatGPT checkout 创建 Stripe checkout session
- Stripe init 预热 PayPal PM
- 可选 promo region 调整到 0 amount
- 首选 `https://api.stripe.com/v1/elements/express_billing_agreement` 生成 `paypal_billing_agreement_token`
- 回退 inline confirm / approve + poll

这解释了为什么 `/Users/mac/Downloads/openai-paypal-main` 需要和 fresh BA 生成器配合：它负责 PayPal BA approval 端，AutoTeam-F 负责 OpenAI/Stripe 侧 BA 生成。

## Guest card 分支结论

从 Weasley source map 看，`approveGuestPaymentWithCreditCard` 存在于 GraphQL schema，auth state 是 `ANONYMOUS`，但当前 Weasley app 没有实际调用文件；当前前端 guest/signup onboarding 用的是：

- `onboardGuest` 或 `signUpNewMember` 创建 guest/signup buyer + funding options
- `ApproveOnboardPaymentMutation` 完成 approval

因此 `approveGuestPaymentWithCreditCard` 更像普通 guest checkout / Fastlane 兼容 resolver，不是当前 BA `BILLING_WITHOUT_PURCHASE` 的主路径。它不能替代 signup/onboard 的 FI acceptance；即便 live shape 可用，也会在 card/FI validation 层受限。

## 当前 live 阻塞

本地协议字段已经收敛到 PayPal 接受 GraphQL shape 的程度；真实成功支付仍缺少两类合法状态之一：

1. `signupNewMember → approveGuestSignUpPayment`：需要 PayPal 接受的真实 US funding instrument；随机/合成 FI 会被 PayPal 风控/校验拒绝。
2. `approveMemberPayment`：需要合法 PayPal buyer 登录/remembered/EUAT auth state + 钱包里的 `primaryFundingOptionId`。

## 待落代码候选（等待同意）

- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/patches/openai-paypal-main-us-runner-schema-weasley-member-v5-draft.diff`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/patches/openai-paypal-main-us-schema-weasley-approve-applyable.diff`

未修改 `/Users/mac/code/my/AutoTeam-F` 业务代码。

## 追加进展：v7 guest/onboard/direct 分支（2026-07-23 23:12 CST）

本轮在隔离工作副本 `/tmp/openai-paypal-main-protocol-work` 上补齐了两个以前只停在 source map 结论的分支，没有修改 `AutoTeam-F` 业务代码，也没有修改 `/Users/mac/Downloads/openai-paypal-main` 原目录：

1. `onboardGuest → ApproveOnboardPaymentMutation`
   - 增加 `ONBOARD_GUEST_MUTATION` 草案和 `_phase_onboard_guest_probe()`。
   - mock harness 已验证：guest buyer、access token、funding instrument id 能被保存。
   - 对 fresh BA/EC 做了无卡 live shape probe：resolver 已到达，返回 `fi is missing`；说明当前 BA/EC 下 `onboardGuest` resolver 可达，但真实成功仍需要 FI。

2. `approveGuestPaymentWithCreditCard` direct
   - 增加 `APPROVE_GUEST_PAYMENT_WITH_CREDIT_CARD_MUTATION` 草案和 `_phase_guest_card_direct_approve()`。
   - mock harness 已验证：可解析 `completedPaymentInfo.transactionState=COMPLETED`、回跳 returnUrl、保存 buyer/FI。
   - 对 fresh BA/EC 做了无卡/无 paymentToken live shape probe：resolver 已到达，返回 `GUEST_PAYMENT_INTEGRITY_VALIDATION_FAILED`；没有 GraphQL validation/auth-state 错误，也没有发起真实支付。
   - 结论：这个 direct resolver 真实存在，但需要 `integrityToken`（schema 描述为 HS256 request integrity JWT）和可接受 card/paymentToken；当前 Weasley BA UI 主路径仍不是它。

新增证据：

- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/onboard_guest_v7_patch_test_20260723.json`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/onboard_guest_live_shape_probe_20260723.json`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/guest_card_direct_v6_patch_test_20260723.json`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/guest_card_direct_live_shape_probe_20260723.json`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro/acceptance_v7_run_20260723.jsonl`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/patches/openai-paypal-main-guest-onboard-card-direct-v7-on-v5-draft.diff`
- `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/paypal_terminal_approval_path_matrix_v7_20260723.json`

当前最强结论：

- Fresh BA 当前仍可进 Phase0 并拿到 EC。
- `onboardGuest` 和 `approveGuestPaymentWithCreditCard` 两个 guest resolver 都能在 live PayPal GraphQL 上到达 resolver 层。
- 剩余阻塞已经从“协议 shape 是否正确”收敛为“真实 FI / integrityToken / buyer auth state”三类运行态条件。
