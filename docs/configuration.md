# 配置说明

AutoToken-F 优先从环境变量读取配置。本地部署通常使用项目根目录 `.env`，Docker 部署使用 `data/.env`。

## 最小配置

```env
MAIL_PROVIDER=cloudflare_temp_email
CLOUDFLARE_TEMP_EMAIL_BASE_URL=https://example.com/api
CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD=your_password
CLOUDFLARE_TEMP_EMAIL_DOMAIN=@example.com

CPA_URL=http://127.0.0.1:8317
CPA_KEY=your_key
API_KEY=change-me
```

`API_KEY` 为空时 Web/API 不启用鉴权。公网或共享机器部署必须设置。

## Mail Provider 切换

`MAIL_PROVIDER` 支持：

| 值 | 说明 |
|----|------|
| `cloudflare_temp_email` | 默认推荐，适合 Cloudflare Workers 临时邮箱服务 |
| `cloud-mail` | 社区 cloud-mail 服务 |
| `outlook` | 使用已有 Outlook/Hotmail 账号池读取验证码 |
| `icloud` | 使用已有 iCloud 账号池和收码链接读取验证码 |
| `luckmail` | 使用 LuckMail 已购邮箱 token 池 |

### cloudflare_temp_email

```env
MAIL_PROVIDER=cloudflare_temp_email
CLOUDFLARE_TEMP_EMAIL_BASE_URL=https://example.com/api
CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD=your_password
CLOUDFLARE_TEMP_EMAIL_DOMAIN=@example.com
```

### cloud-mail

```env
MAIL_PROVIDER=cloud-mail
CLOUD_MAIL_API_URL=https://your-cloud-mail.example.com
CLOUD_MAIL_ADMIN_EMAIL=admin@example.com
CLOUD_MAIL_ADMIN_PASSWORD=your_password
CLOUD_MAIL_DOMAIN=@example.com
```

### outlook

```env
MAIL_PROVIDER=outlook
OUTLOOK_ACCOUNTS_FILE=data/outlook_accounts.txt
OUTLOOK_PROVIDER_PRIORITY=imap_old,imap_new,graph_api
OUTLOOK_REGISTER_CODE_TIMEOUT=30
```

账号池格式：

```text
email@outlook.com----mail_password
email@outlook.com----mail_password----client_id----refresh_token
email@outlook.com----https://mailapi.icu/key?type=html&orderNo=xxxx
```

### icloud

```env
MAIL_PROVIDER=icloud
ICLOUD_ACCOUNTS_FILE=data/icloud_accounts.txt
```

账号池格式：

```text
email@icloud.com----https://icloud-api.top/show/xxx/email@icloud.com
```

### luckmail

```env
MAIL_PROVIDER=luckmail
LUCKMAIL_BASE_URL=https://mail.luckyous.com
LUCKMAIL_ACCOUNTS_FILE=data/luckmail_accounts.txt
LUCKMAIL_API_KEY=
LUCKMAIL_PROJECT_CODE=openai
LUCKMAIL_EMAIL_TYPE=ms_graph
LUCKMAIL_REUSE_PURCHASED_CACHE=0
```

账号池格式：

```text
email@outlook.my----tok_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

默认不会复用 SQLite 里历史自动购买的 LuckMail 缓存，避免旧缓存邮箱再次进入注册池。确认缓存属于当前 LuckMail 账号时，可设置 `LUCKMAIL_REUSE_PURCHASED_CACHE=1`。

## CPA

```env
CPA_URL=http://127.0.0.1:8317
CPA_KEY=your_key
```

CPA 用于保存和恢复 Codex CLI 认证文件。轮转完成后可以将 active 账号认证同步到 CPA，也可以从 CPA 反向导入到本地。

## OAuth

```env
OAUTH_BROWSER_MODE=protocol
POST_REGISTER_OAUTH_ENABLED=false
OAUTH_CHROME_CDP_URL=http://127.0.0.1:9222
```

`OAUTH_BROWSER_MODE=protocol` 是默认模式，优先使用纯协议 OAuth。需要人工浏览器协作时，可以使用 Chrome CDP 相关配置。

## 协议注册邮箱 OTP 预算

```env
OPENAI_EMAIL_OTP_VERIFY_MAX_ATTEMPTS=2
OPENAI_EMAIL_OTP_MAX_RESENDS=1
```

每次协议注册尝试只允许一次初始邮箱 OTP mutation；`email-otp/send` 与
`passwordless/send-otp` 共用该额度。默认最多再调用一次
`email-otp/resend`，并最多校验两个不同的新验证码。网络 timeout 发生在发码
调用后时同样消耗额度，系统不会改用另一个发码端点级联重试。

## 协议注册安全默认值

- `PROTOCOL_REGISTER_ENGINE=python` 仍是默认引擎；Go daemon 是 opt-in MVP。
- `OPENAI_HTTP_IMPERSONATE=chrome136` 在一次 Python 尝试开始时读取一次；TLS
  错误按网络失败处理，不会在尝试内轮换 profile 或替换 cookie jar。
- HTTP transport 只对普通 `GET/HEAD/OPTIONS` 使用安全重试；OTP send 这类以
  GET 表达的 mutation 使用专用零重试 adapter，所有 POST mutation 均不自动重试。
- Sentinel SDK 执行不可用时默认 fail-closed；synthetic fallback 仅保留显式
  legacy 兼容开关，失败后不会继续发送注册 mutation。
- 邮箱 OTP 预算为一次初始请求、默认一次 resend，并默认最多校验两个不同新码。
- Go 到 Python 的自动 fallback 只允许发生在 daemon 启动或健康检查失败时；
  `/v1/register` 请求发出后的 timeout、连接中断或无效响应属于 indeterminate，
  必须停止当前尝试，不能通过 Python 重放。

## Sentinel SDK 自动跟随

协议注册默认从 OpenAI Sentinel 的官方运行时 frame 页面
`https://sentinel.openai.com/backend-api/sentinel/frame.html` 发现当前 `sdk.js`，
无需手工维护版本号。该页面位于 OpenAI 官方子域，但属于线上运行时入口，
因此实现同时保留缓存、last-known-good 和内置版本回退。

```env
OPENAI_SENTINEL_SDK_URL=
OPENAI_SENTINEL_VERSION=
OPENAI_SENTINEL_SDK_TTL_SECONDS=21600
OPENAI_SENTINEL_ALLOW_SYNTHETIC_FALLBACK=0
```

解析优先级如下：

1. `OPENAI_SENTINEL_SDK_URL`：临时固定完整 SDK 地址，仅接受
   `https://sentinel.openai.com/sentinel/<version>/sdk.js`。
2. `OPENAI_SENTINEL_VERSION`：临时固定版本，并自动拼成官方地址。
3. TTL 内的本地缓存。
4. 线上 frame 页面实时发现。
5. 发现失败时使用过期的 last-discovered 缓存。
6. 无可用缓存时使用内置版本 `20260219f9f6`。

QuickJS 会再按“本次解析版本 → 最近一次完整执行成功的 last-known-good →
内置版本”尝试。所有候选均不可执行时，协议注册默认 fail-closed，不会生成
synthetic token，也不会继续发送后续注册请求。此时应停止任务，或由操作员
显式选择项目支持的浏览器注册流程。

默认 TTL 为 `21600` 秒（6 小时），设为 `0` 可让每次注册都检查线上版本，
但高并发场景建议保留默认值。Windows 缓存通常位于
`%TEMP%/openai-sentinel-demo/latest.json`；运行验证记录位于同目录的
`last-good.json`，各版本 SDK 位于版本子目录。旧的纯 Python synthetic fallback
仅可通过 `OPENAI_SENTINEL_ALLOW_SYNTHETIC_FALLBACK=1` 显式恢复以兼容旧部署，
该路径不受支持，默认保持关闭。QuickJS 子进程只继承启动 Node 所需的系统变量
和 Sentinel 运行参数，不继承应用密码、API key 或其他配置 secrets。

## Playwright 代理

```env
PLAYWRIGHT_PROXY_URL=socks5://user:pass@host:1080
PLAYWRIGHT_PROXY_BYPASS=localhost,127.0.0.1
```

如果浏览器 OAuth 使用代理，建议显式绕过 localhost，避免本地回调被代理截走。

## CloakBrowser 注册

注册页勾选“使用 Cloak 无头模式”后，会用 CloakBrowser 替代本地 Playwright Chromium 执行标准邮箱注册。该模式默认无头运行，并复用注册任务里传入的固定代理、代理池或动态代理 API。

```env
CLOAK_HEADLESS=true
CLOAK_HUMANIZE=true
CLOAK_GEOIP=true
CLOAK_USE_PROXY=true
CLOAK_LOCALE=
CLOAK_TIMEZONE=
CLOAK_LICENSE_KEY=
CLOAK_FINGERPRINT_SEED=
CLOAK_USER_DATA_DIR=
CLOAK_EXTRA_ARGS=
CLOAK_KEEP_BROWSER_OPEN=false
```

常用调试方式：把 `CLOAK_HEADLESS=false` 显示窗口；把 `CLOAK_KEEP_BROWSER_OPEN=true` 保留浏览器。需要固定地区画像时可显式设置 `CLOAK_LOCALE=ja-JP`、`CLOAK_TIMEZONE=Asia/Tokyo` 等。

## 自动巡检

```env
AUTO_CHECK_INTERVAL=300
AUTO_CHECK_THRESHOLD=10
AUTO_CHECK_MIN_LOW=2
```

API 模式下后台巡检会按间隔检查额度，低于阈值时触发轮转。

## 对账策略

```env
RECONCILE_KICK_ORPHAN=true
RECONCILE_KICK_GHOST=true
```

`orphan` 表示 workspace 仍占席但本地认证文件缺失。`ghost` 表示 workspace 有成员但本地完全无记录。默认会自动清理；如果需要人工确认，可以改成 `false`。

## 支付和 GoPay

支付相关配置很多，建议只在需要绑定任务时配置：

| 前缀 | 用途 |
|------|------|
| `ROXYBROWSER_*` | 浏览器自动化使用 RoxyBrowser 模式 |
| `CLOAK_*` | 注册模块使用 CloakBrowser 无头模式 |
| `GOPAY_AUTO_SIGNUP_*` | 自动注册 GoPay 钱包 |
| `REKBERINAJA_*` | GoPay 充值辅助 |
| `WHATSAPP_*`, `ANDROID_ADB_PATH` | 从 Android/ADB 读取 WhatsApp OTP |

这些配置通常包含服务商 token、手机号池、登录态或钱包数据，必须只保存在本地 `.env` 或 `data/.env`，不要提交到 Git。

## Go protocol registration service

`PROTOCOL_REGISTER_ENGINE=python` 保持 Python 参考链路。设置为 `go` 会把
`register_mode=protocol` 路由到本机 `protocol-registerd`；在 readiness 与状态机
一致性验证完成前，该服务保持 opt-in，不应直接扩大线上并发。

| Variable | Default | Purpose |
|---|---:|---|
| `GO_PROTOCOL_REGISTER_URL` | `http://127.0.0.1:18787` | Local service endpoint |
| `GO_PROTOCOL_REGISTER_AUTO_START` | `1` | Python may start the local binary |
| `GO_PROTOCOL_REGISTER_BIN` | `bin/protocol-registerd.exe` | Windows binary path |
| `GO_PROTOCOL_MAX_CONCURRENCY` | `50` | MVP daemon admission ceiling；不是建议的上游认证并发 |
| `GO_PROTOCOL_FALLBACK_PYTHON` | `1` | 仅 daemon 启动/健康检查失败时允许 Python fallback |
| `GO_PROTOCOL_TRACE` | `0` | Include non-secret trace events |
| `GO_PROTOCOL_IMPERSONATE` | `chrome143,...,chrome152` | MVP legacy UA label；Go 标准 TLS 不构成对应浏览器 profile |

Go register 调用一旦开始，客户端会把后续网络 timeout、连接中断和无效 JSON
响应标记为 `indeterminate` 并直接返回错误。即使
`GO_PROTOCOL_FALLBACK_PYTHON=1`，这些错误也不会触发 Python 注册。
