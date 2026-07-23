# 继续笔记 — openai-paypal-main 必要信息核验

- PayPal 侧本地协议闭环已在 `/Users/mac/Downloads/openai-paypal-main` 形成：`CreateMemberAccountMutation(no FI)` + `ApproveMemberPaymentMutation(primaryFundingOptionId=null)`。
- 历史 fresh BA 成功样本显示 Stripe payment methods 曾经包含 `paypal`；当前 fresh BA 失败样本显示 ChatGPT checkout 可 200，但 Stripe 只返回 `card`。
- 当前研究重点应从 PayPal approve 协议转到 BA 提链前置条件：merchant/Stripe session 是否暴露 PayPal funding source。
- AutoTeam-F 业务代码保持未改。
