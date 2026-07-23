# PayPal 本地协议支付链路继续研究 — 2026-07-23 23:35 CST

## 本轮新增验证

1. 重新跑 v7 离线 acceptance：通过。
   - 证据：`.open-reverselab/exports/paypal-openai-main/repro/acceptance_v7_rerun_20260723_233129.jsonl`

2. 继续检查当前 PayPal Weasley source map，补抽 `createMemberAccount.gql.ts`。
   - 证据：`.open-reverselab/exports/paypal-openai-main/weasley_extracted_extra/src_components_Form_graphql_mutations_createMemberAccount.gql.ts`

3. 从 `generated_graphql.tsx` 提取支付相关 mutation schema/args：
   - `createMemberAccount`: ANONYMOUS，可无 card/bank；Weasley 注释说明用于创建 account，字段只要求 token、firstName、lastName，UI gql 还要求 email/phone。
   - `approveGuestSignUpPayment`: LOGGEDIN/IDENTIFIED，signup/guest flow 终态 approve。
   - `approveMemberPayment`: LOGGEDIN/REMEMBERED/IDENTIFIED，注释明确 Requires `primaryFundingOptionId`，虽然 TS args 标注为 optional。
   - `attemptSetStickyFi`: LOGGEDIN/IDENTIFIED，用于 BA signup flow 设置 sticky/primary FI。
   - 证据：`.open-reverselab/exports/paypal-openai-main/weasley_mutation_schema_payment_fields_20260723.json`
   - 证据：`.open-reverselab/exports/paypal-openai-main/weasley_mutation_args_payment_fields_20260723.json`

4. 构造 v8 候选离线 harness：`createMemberAccount(no FI) -> approveGuestSignUpPayment(skip sticky when no FI)`。
   - 证据脚本：`.open-reverselab/exports/paypal-openai-main/repro/test_create_member_no_fi_candidate_v8.py`
   - 证据结果：`.open-reverselab/exports/paypal-openai-main/create_member_no_fi_candidate_v8_offline_20260723.json`

## 新增判断

`createMemberAccount` 是当前源码里唯一明确“无 card/bank 创建 buyer auth”的 mutation；它比 `SignUpNewMember(card:null)` 更接近 `allowBillingAgreementWithoutBackupFundingSource=true` 的无备付资金候选链路。

但它在 Weasley 原始逻辑中只在 BNPL/paylater 分支触发：

- `getMutationName(isSignup, isPayLater)` 中 `isPayLater` 返回 `createMemberAccount`；
- createMember 成功后 Weasley BNPL 分支走 `redirectToMember(...)`，不是直接 `approvePayment()`；
- 普通 BA signup/onboard 仍需要 FI，再调用 `attemptSetStickyFi(token, instrumentId)` + `approveGuestSignUpPayment(token)`。

因此 v8 不是已证明成功链，而是下一条最值得验证的本地候选：

```text
Fresh BA -> EC -> SMS/OTP -> createMemberAccount(no FI)
  -> 保存 buyer.auth.accessToken/EUAT
  -> 终态 A: approveGuestSignUpPayment(token), 且没有 instrumentId 时跳过 attemptSetStickyFi
  -> 终态 B: approveMemberPayment(token, primaryFundingOptionId omitted/null), 仅当 BA flag 允许 no backup FI
```

## 仍然未成功的原因

当前已证明：协议 shape、GraphQL operation、headers、risk/MTR/DataDome 本地执行框架都能到 resolver 层；未证明的不是“字段怎么写”，而是 PayPal 真实运行态：

- signup/onboard 卡在真实 FI validation；
- direct guest card 卡在 integrityToken + accepted paymentToken/card；
- member approve 卡在 buyer auth + wallet/primaryFundingOptionId；
- v8 createMember no-FI 还缺受控 live 验证，且 terminal approve 是否能无 FI 由 PayPal 服务端状态决定。

## 未改动

未修改 `/Users/mac/code/my/AutoTeam-F` 业务代码。
