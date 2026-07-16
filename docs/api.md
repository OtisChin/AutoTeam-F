# HTTP API 文档

启动后访问 `http://localhost:8787/docs` 查看 Swagger 交互式文档。

所有 `/api/*` 端点需要：

```text
Authorization: Bearer <API_KEY>
```

但以下接口例外：
- `/api/auth/check`
- `/api/setup/status`
- `/api/setup/save`

## 即时返回接口

这些接口直接返回结果，不创建后台任务。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/bind/link` | 生成支付链接 |
| GET | `/api/auth/check` | 验证 API Key |
| GET | `/api/setup/status` | 检查配置是否完整 |
| POST | `/api/setup/save` | 保存初始配置 |
| GET | `/api/status` | 账号状态 + 实时额度 |
| GET | `/api/accounts` | 所有账号列表 |
| GET | `/api/accounts/active` | 活跃账号 |
| GET | `/api/accounts/standby` | 待命账号 |
| GET | `/api/team/members` | Team 全部成员（含外部成员与邀请） |
| POST | `/api/team/members/remove` | 移出成员 / 取消邀请 |
| GET | `/api/logs` | 最近日志（支持 `?limit=100&since=0`） |
| GET | `/api/cpa/files` | CPA 认证文件列表 |
| GET | `/api/config/auto-check` | 巡检配置 |
| PUT | `/api/config/auto-check` | 修改巡检配置（运行时生效） |
| POST | `/api/sync` | 同步 active 认证文件到 CPA |
| POST | `/api/sync/from-cpa` | 从 CPA 反向同步认证文件到本地（含去重） |
| POST | `/api/sync/accounts` | 从 Team / auths 对账到本地账号池 |
| POST | `/api/accounts/{email}/kick` | 将 active 账号移出 Team |
| DELETE | `/api/accounts/{email}` | 删除本地管理账号及其资源 |

### Team 成员移除

`POST /api/team/members/remove`

请求体：

```json
{
  "email": "user@example.com",
  "user_id": "123",
  "type": "member"
}
```

- `type = member`：从 Team 中移出
- `type = invite`：取消邀请

### 生成支付链接

`POST /api/bind/link`

请求体示例：

```json
{
  "access_token": "eyJ...",
  "entry_point": "team_workspace_purchase_modal",
  "plan_name": "chatgptteamplan",
  "team_plan_data": {
    "workspace_name": "我的团队",
    "price_interval": "month",
    "seat_quantity": 2
  },
  "billing_details": {
    "country": "US",
    "currency": "USD"
  },
  "cancel_url": "https://chatgpt.com/?promoCode=STRIPEPERKSGPT4BIZ",
  "promo_code": "STRIPEPERKSGPT4BIZ",
  "checkout_ui_mode": "hosted"
}
```

说明：

- `access_token`：目标账号的 ChatGPT access token
- `entry_point`：Team 长链接传 `team_workspace_purchase_modal`
- `plan_name`：如 `chatgptteamplan` / `chatgptplusplan`
- `team_plan_data`：团队订阅时传入工作区名称、计费周期和席位数
- `billing_details`：国家和货币
- `cancel_url`：可选，取消支付后的回跳地址
- `promo_code`：可选，Team 优惠码
- `checkout_ui_mode`：`hosted` 时优先返回长链接 `url`

Plus 兼容旧参数：

- `promo_campaign`：Plus 仍可传 `{ "promo_campaign_id": "...", "is_coupon_from_query_param": false }`

## 后台任务接口

这些接口返回 `202 Accepted + task_id`。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/rotate` | 智能轮转 `{"target": 5}` |
| POST | `/api/tasks/check` | 检查额度，`{"include_standby": false}` 追加探测 standby 池（限速 1.5s/号 + 24h 去重） |
| POST | `/api/tasks/add` | 自动注册并添加新账号 |
| POST | `/api/tasks/fill` | 补满成员 `{"target": 5}` |
| POST | `/api/tasks/cleanup` | 清理成员 `{"max_seats": null}` |
| POST | `/api/tasks/bind-card` | 启动绑卡任务 |
| POST | `/api/tasks/gopay-bind` | 启动 GoPay 自助绑卡任务 |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{task_id}` | 任务详情 |

> 同一时间只允许一个 Playwright 操作；如果有任务执行中，新请求可能返回 `409 Conflict`。

### 绑卡任务

`POST /api/tasks/bind-card`

请求体：

```json
{
  "email": "user@example.com",
  "card_item_id": "card-001",
  "checkout_url": "https://chatgpt.com/checkout/...",
  "proxy_url": "socks5://user:pass@host:port",
  "proxy_label": "res-us-01",
  "manual_confirm": true,
  "autofill_enabled": true,
  "billing_name": "James Smith",
  "billing_phone": "1234567890",
  "billing_country": "US",
  "billing_state": "NY",
  "billing_city": "New York",
  "billing_zip": "10001",
  "billing_address1": "123 Main St",
  "billing_address2": "",
  "timeout_seconds": 900
}
```

说明：

- `email`：号池账号邮箱，要求本地存在可用 `auth_session` 或 `auth_file`
- `card_item_id`：卡池中状态为 `unused` 的卡记录 ID
- `checkout_url`：由 `/api/bind/link` 生成，或手动提供的 checkout 链接
- `proxy_url`：可选。传值时覆盖全局 Playwright 代理；不传时回退到 `.env` 里的全局代理配置
- `proxy_label`：可选。只用于审计和结果回写
- `manual_confirm`：`true` 时保留浏览器窗口等待人工确认最终支付结果；远程服务器或 Docker 部署通常无法直接操作该浏览器，不建议开启

### GoPay 绑卡任务

`POST /api/tasks/gopay-bind`

请求体：

```json
{
  "email": "user@example.com",
  "checkout_url": "",
  "gopay_auto_signup": false,
  "gopay_auto_signup_sms_provider": "smscloud",
  "gopay_auto_signup_hero_sms_api_key": "",
  "gopay_auto_signup_hero_sms_base_url": "https://hero-sms.com/stubs/handler_api.php",
  "gopay_auto_signup_hero_sms_country": "6",
  "gopay_auto_signup_hero_sms_service": "ni",
  "gopay_auto_signup_hero_sms_timeout": "120",
  "gopay_auto_signup_hero_sms_max_price": "0.045",
  "gopay_auto_signup_smscloud_base_url": "https://smscloud.sbs/api",
  "gopay_auto_signup_smscloud_country": "6",
  "gopay_auto_signup_smscloud_service": "ni",
  "gopay_auto_signup_smscloud_max_price": "",
  "gopay_auto_signup_smscloud_timeout": "120",
  "phone_number": "+6287761973970",
  "sms_url": "https://it.tgflare.com/api/record?token=...",
  "gopay_pin": "558023",
  "proxy_url": "socks5://user:pass@host:port",
  "proxy_label": "res-id-01",
  "timeout_seconds": 900
}
```

说明：

- `email`：号池账号邮箱
- `checkout_url`：可选，留空时后台会自动生成印尼区 Plus checkout 链接
- `gopay_auto_signup`：可选。`true` 时先通过短信服务商自动注册 GoPay 钱包，再继续绑定；此时 `phone_number` / `sms_url` 可留空，但仍需提供 `gopay_pin`
- `gopay_auto_signup_sms_provider`：可选。`smscloud`（默认）或 `hero_sms`
- `gopay_auto_signup_hero_sms_*`：可选。本次任务使用的 hero-sms 配置；留空时回退到后端 `.env` 中的 `GOPAY_AUTO_SIGNUP_HERO_SMS_*`。`gopay_auto_signup_hero_sms_max_price` 会作为 `maxPrice` 传给 `getNumber`，例如 `0.045`
- `gopay_auto_signup_smscloud_*`：可选。本次任务使用的 smscloud 配置；留空时回退到后端 `.env` 中的 `GOPAY_AUTO_SIGNUP_SMSCLOUD_*`。smscloud 取号接口实际需要网站登录后的 `XI_TOKEN`，建议配置 `GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN`
- Rekberinaja 充值：可选。设置页或 `.env` 中启用 `REKBERINAJA_TRANSFER_ENABLED=1` 后，自动注册 GoPay 钱包完成后会先用 Rekberinaja 站内余额充值默认 `Go Pay 1.000`，到账后再进入绑定。默认关闭；关闭时注册/PIN 完成后会主动查询 GoPay 余额，默认在 30、60、120 秒后各查一次；任意一次查到余额 >= 1rp 就进入绑定，三次仍未到账会丢弃该 GoPay 钱包并重新注册新钱包。Rekberinaja 未提供公开开发者文档，当前集成使用其前端调用的 JSON 接口：登录、查站内余额、创建 GoPay 充值订单、`/transaction/{id}/pay` 扣余额、`/transaction/{id}/order-product` 轮询状态。
- `phone_number`：GoPay 手机号
- `sms_url`：短信验证码接口 URL
- `gopay_pin`：用户提供的 GoPay PIN
- `proxy_url` / `proxy_label`：可选，任务级代理覆盖
- `timeout_seconds`：等待最终结果的超时时间，默认 900 秒


## 管理员运维

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/admin/reconcile?dry_run=0` | 对账修复：扫描 workspace 实际成员 vs 本地 `accounts.json`，识别**残废 / 错位 / 耗尽未抛弃 / ghost / over-cap**五类异常并按 `RECONCILE_KICK_ORPHAN` / `RECONCILE_KICK_GHOST` 决定 KICK 或打标记。`dry_run=1` 仅预测不动账户（包含第二轮 over-cap 预测），返回结构化诊断 dict（`kicked` / `orphan_kicked` / `orphan_marked` / `misaligned_fixed` / `exhausted_marked` / `ghost_kicked` / `ghost_seen` / `over_cap_kicked` / `flipped_to_active`） |

## 管理员登录

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/status` | 管理员状态 |
| POST | `/api/admin/login/start` | 开始登录 `{"email": "admin@example.com"}` |
| POST | `/api/admin/login/session` | 手动导入 session_token `{"email": "admin@example.com", "session_token": "..."}` |
| POST | `/api/admin/login/password` | 提交密码 `{"password": "..."}` |
| POST | `/api/admin/login/code` | 提交验证码 `{"code": "123456"}` |
| POST | `/api/admin/login/workspace` | 选择组织 `{"option_id": "0"}` |
| POST | `/api/admin/login/cancel` | 取消登录 |
| POST | `/api/admin/logout` | 清除登录态 |

## 主号 Codex 同步

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/main-codex/status` | 同步状态 |
| POST | `/api/main-codex/start` | 开始同步 |
| POST | `/api/main-codex/password` | 提交密码 |
| POST | `/api/main-codex/code` | 提交验证码 |
| POST | `/api/main-codex/cancel` | 取消同步 |

## 手动 OAuth 导入

后端先生成 Codex OAuth 链接，并尝试在 `localhost:1455` 自动接收回调；如果自动回调不可用，也可以手动提交回调 URL。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/manual-account/status` | 当前手动 OAuth 状态 |
| POST | `/api/manual-account/start` | 开始流程，返回 `auth_url` 与状态信息 |
| POST | `/api/manual-account/callback` | 提交回调 URL |
| POST | `/api/manual-account/cancel` | 取消流程 |

### `/api/manual-account/status` 关键字段

| 字段 | 说明 |
|------|------|
| `status` | `idle / pending_callback / completed / error` |
| `auth_url` | 当前 OAuth 链接 |
| `callback_received` | 是否已收到回调 |
| `callback_source` | `auto` 或 `manual` |
| `auto_callback_available` | 本地自动回调服务是否启动成功 |
| `account` | 完成后导入的账号信息 |

## 调用示例

```bash
# 查看账号状态
curl -H "Authorization: Bearer YOUR_KEY" \
  http://localhost:8787/api/status

# 触发轮转
curl -X POST -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"target": 5}' \
  http://localhost:8787/api/tasks/rotate

# 从 CPA 拉取认证文件到本地
curl -X POST -H "Authorization: Bearer YOUR_KEY" \
  http://localhost:8787/api/sync/from-cpa

# 生成手动 OAuth 链接
curl -X POST -H "Authorization: Bearer YOUR_KEY" \
  http://localhost:8787/api/manual-account/start
```
