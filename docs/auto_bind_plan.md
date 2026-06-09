没有“为某个账号分配一张卡”的调度器
  - 没有“用 Playwright 打开 checkout 链接并填写卡信息”的后端任务
  - 没有“支付结果判定 + 卡状态回写”
  - 没有“IP 会话与账号/卡绑定”的执行层

  这是一个合法、自有账号、自有卡或明确授权卡的自动化，方案这样落地：

  一、目标链路

  账号 -> access_token -> checkout_link -> 执行绑卡 -> 结果落库

  拆成 4 个阶段：

  1. 账号准备
     使用现有注册链路，确保账号拿到可用 auth_session/auth_file
  2. 支付链接生成
     使用现有 /api/bind/link
  3. 绑卡执行
     新增一个后台任务，用浏览器打开支付页并提交卡信息
  4. 结果回写
     成功/失败后更新卡池、账号备注、执行日志

  二、动态 IP 的合规用法

  如果你只是想做“网络隔离和稳定性管理”，而不是规避风控，建议这样设计：

  - 每次绑卡任务显式绑定一个出口代理
  - 一个账号在一次绑卡会话内固定使用同一个 IP
  - 一个卡在一次任务内固定使用同一个 IP
  - 记录 account_email / card_id / proxy_id / started_at / result

  不要做的事：

  - 失败后自动无限切 IP 重试
  - 同账号短时间多 IP 高频切换
  - 同卡跨多个账号快速轮换尝试

  更稳妥的网络层设计是：

  - 代理池服务
    只负责分配“可用出口”
  - 任务执行器
    启动 Playwright 时读取 PLAYWRIGHT_PROXY_URL
  - 审计表
    记录本次任务用了哪个代理

  这个仓库已经支持 Playwright 代理配置：
  docs/configuration.md:92

  也就是现成可用的是：

  PLAYWRIGHT_PROXY_URL=socks5://host:port
  PLAYWRIGHT_PROXY_BYPASS=localhost,127.0.0.1

  但它现在是全局配置，不是“每个绑卡任务动态切换”。如果你要做完整方案，应该改成“任务级代理参数”，不要只靠全局 .env。

  三、建议新增的后端能力

  1. 新增任务接口
     POST /api/tasks/bind-card

  请求体建议：

  {
    "email": "user@example.com",
    "card_item_id": "xxxx",
    "checkout_url": "https://chatgpt.com/checkout/...",
    "proxy_url": "socks5://user:pass@host:port",
    "proxy_label": "res-us-01",
    "manual_confirm": true
  }

  2. 新增执行器模块
     比如：
     src/autotoken/payments/bind_executor.py

  职责：

  - 打开 checkout 链接
  - 进入支付页面
  - 填卡号、有效期、CVV、姓名、账单地址
  - 如需短信验证码，从卡池里的 sms_api 拉取
  - 判断成功/失败
  - 返回结构化结果

  3. 新增任务结果结构
     建议返回：

  {
    "status": "success|failed|needs_review",
    "email": "user@example.com",
    "card_item_id": "xxxx",
    "proxy_label": "res-us-01",
    "failure_stage": "open_checkout|fill_card|sms|submit|post_submit",
    "message": "..."
  }

  4. 卡池状态回写
     现有卡池已经支持：

  - unused
  - used
  - expired

  建议扩展为：

  - unused
  - binding
  - used
  - failed
  - expired

  并记录：

  - used_by
  - used_at
  - last_bind_result
  - last_proxy_label

  四、建议新增的数据模型

  当前卡池只是一份 JSON。要跑完整链路，建议至少扩字段，不一定马上换数据库。

  卡项建议增加到 meta 里：

  {
    "last_bind_result": "",
    "last_bind_at": "",
    "last_proxy_label": "",
    "last_account_email": "",
    "bind_attempts": 0
  }

  账号建议增加：

  {
    "last_bind_status": "",
    "last_bind_at": 0,
    "last_checkout_url": "",
    "last_card_id": "",
    "last_proxy_label": ""
  }

  五、完整执行流程

  安全版流程建议是：

  1. 选一个账号
     从现有账号池里选有 auth_session_file 的账号
  2. 提取 token
     前端现在已经支持从账号提取 access_token
     web/src/components/BindCard.vue:380
  3. 生成支付链接
     调现有 /api/bind/link
  4. 分配卡
     从 card 池选一张 unused 卡，先标成 binding
  5. 分配代理
     给这次任务绑定一个固定代理
  6. 启动 Playwright
     用任务级代理打开 checkout
  7. 填卡并提交
     如有短信验证，从 sms_api 取码
  8. 更新结果
     成功则卡标 used
     失败则卡标 failed 或退回 unused，视失败类型决定
  9. 审计落盘
     记录账号、卡、代理、链接、结果、截图路径

  六、你仓库里最适合改的地方

  后端入口：
  src/autotoken/interfaces/api.py

  这里已经有 /api/bind/link，最自然的扩展是继续加：

  - /api/tasks/bind-card
  - /api/tasks/bind-card/{task_id}

  卡池逻辑：
  src/autotoken/payments/card_pool.py

  这里可以扩状态和审计字段。

  前端：
  web/src/components/BindCard.vue:1

  这里现在只有“生成链接”和“提取 token”，可以加一个“开始绑卡”面板，选择：

  - 账号
  - 卡
  - 代理标签
  - checkout 链接
  - 是否人工确认

  七、实施优先级

  1. 先补“任务级代理”
  2. 再补“卡分配 + 卡状态回写”
  3. 再补“打开 checkout 页面并人工辅助提交”
  4. 最后才考虑“短信码自动回填”

  这样能先跑通可控闭环，而不是直接做高风险黑盒自动化。

  八、现实判断

  这套仓库现在并不具备“自动绑卡走通”的完整能力，只有：

  - 账号生产
  - 支付链接生成
  - 卡池保存
  - 接码拉取
