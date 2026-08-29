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

## Sentinel SDK 自动跟随

协议注册默认从 OpenAI Sentinel 的官方运行时 frame 页面
`https://sentinel.openai.com/backend-api/sentinel/frame.html` 发现当前 `sdk.js`，
无需手工维护版本号。该页面位于 OpenAI 官方子域，但属于线上运行时入口，
因此实现同时保留缓存、last-known-good 和内置版本回退。

```env
OPENAI_SENTINEL_SDK_URL=
OPENAI_SENTINEL_VERSION=
OPENAI_SENTINEL_SDK_TTL_SECONDS=21600
```

解析优先级如下：

1. `OPENAI_SENTINEL_SDK_URL`：临时固定完整 SDK 地址，仅接受
   `https://sentinel.openai.com/sentinel/<version>/sdk.js`。
2. `OPENAI_SENTINEL_VERSION`：临时固定版本，并自动拼成官方地址。
3. TTL 内的本地缓存。
4. 线上 frame 页面实时发现。
5. 发现失败时使用过期的 last-discovered 缓存。
6. 无可用缓存时使用内置版本 `20260219f9f6`。

QuickJS 会再按“本次解析版本 → 最近一次完整求解成功的 last-known-good →
内置版本”尝试，若未来 SDK 的压缩结构发生不兼容变化，不会直接中断全部注册。

默认 TTL 为 `21600` 秒（6 小时），设为 `0` 可让每次注册都检查线上版本，
但高并发场景建议保留默认值。Windows 缓存通常位于
`%TEMP%/openai-sentinel-demo/latest.json`；运行验证记录位于同目录的
`last-good.json`，各版本 SDK 位于版本子目录。QuickJS 与纯 Python fallback
共用同一次解析结果，避免生成 token 时出现 SDK 地址不一致。

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

`PROTOCOL_REGISTER_ENGINE=python` keeps the legacy Python protocol path. Set `PROTOCOL_REGISTER_ENGINE=go` to route `register_mode=protocol` through the local `protocol-registerd` service.

| Variable | Default | Purpose |
|---|---:|---|
| `GO_PROTOCOL_REGISTER_URL` | `http://127.0.0.1:18787` | Local service endpoint |
| `GO_PROTOCOL_REGISTER_AUTO_START` | `1` | Python may start the local binary |
| `GO_PROTOCOL_REGISTER_BIN` | `bin/protocol-registerd.exe` | Windows binary path |
| `GO_PROTOCOL_MAX_CONCURRENCY` | `50` | Maximum inflight Go registration tasks |
| `GO_PROTOCOL_FALLBACK_PYTHON` | `1` | Use Python path when Go service is unavailable |
| `GO_PROTOCOL_TRACE` | `0` | Include non-secret trace events |
| `GO_PROTOCOL_IMPERSONATE` | `chrome143,chrome144,chrome145,chrome146,chrome147,chrome148,chrome149,chrome150,chrome151,chrome152` | Chrome fingerprint pool or single label |
