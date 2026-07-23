# PayPal 本地协议支付链路追加报告 — v8 no-FI 候选

## 结论更新

`/Users/mac/Downloads/openai-paypal-main` 的必要信息加上 PayPal Weasley source map 已足够还原当前主链，但真实成功仍不能通过随机/合成 FI 达成。新增发现是 `createMemberAccount`：它是 Weasley 中唯一可在 ANONYMOUS 下不带 card/bank 创建 buyer auth 的 mutation，可作为 `allowBillingAgreementWithoutBackupFundingSource=true` 的下一候选，而不是继续重复 `SignUpNewMember(card:null)`。

## 证据

- v7 acceptance rerun: `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/repro/acceptance_v7_rerun_20260723_233129.jsonl`
- server actions map: `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/pay_next_server_actions_20260723.json`
- Weasley mutation fields: `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/weasley_mutation_schema_payment_fields_20260723.json`
- Weasley mutation args: `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/weasley_mutation_args_payment_fields_20260723.json`
- extracted createMemberAccount gql: `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/weasley_extracted_extra/src_components_Form_graphql_mutations_createMemberAccount.gql.ts`
- v8 no-FI candidate offline: `/Users/mac/code/my/AutoTeam-F/.open-reverselab/exports/paypal-openai-main/create_member_no_fi_candidate_v8_offline_20260723.json`

## 路径矩阵更新

| 路径 | 本地状态 | live 阻塞 |
|---|---|---|
| `signUpNewMember -> approveGuestSignUpPayment` | shape/mock 通 | 真实 FI validation |
| `onboardGuest -> approveGuestSignUpPayment` | resolver 可达/mock 通 | FI required |
| `approveGuestPaymentWithCreditCard` | resolver 可达/mock 通 | integrityToken + accepted paymentToken/card |
| `approveMemberPayment` | shape/mock 通 | buyer auth + primaryFundingOptionId；schema 注释仍要求 primaryFundingOptionId |
| `createMemberAccount(no FI) -> approve...` | 新增 v8 candidate/mock 通 | 是否允许 no sticky FI / no primaryFundingOptionId 需受控验证 |
| Official REST / JS SDK / Vault | mock 通 | 缺 PayPal sandbox/live client credentials |

## 下一步只剩两条合规可控路线

1. 使用 PayPal Developer sandbox/live app credentials，按官方 Orders/Subscriptions/Vault flow 本地跑通；这是真正可部署、可维护的协议支付。
2. 若继续 Weasley 内部协议，只能在受控、合法 PayPal buyer/FI 或 sandbox buyer 状态下验证 v8；否则继续重复随机卡、代理、接码不会从协议层解决问题。
