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

### luckmail

```env
MAIL_PROVIDER=luckmail
LUCKMAIL_BASE_URL=https://mail.luckyous.com
LUCKMAIL_ACCOUNTS_FILE=data/luckmail_accounts.txt
LUCKMAIL_API_KEY=
LUCKMAIL_PROJECT_CODE=openai
LUCKMAIL_EMAIL_TYPE=ms_graph
```

账号池格式：

```text
email@outlook.my----tok_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

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

## Playwright 代理

```env
PLAYWRIGHT_PROXY_URL=socks5://user:pass@host:1080
PLAYWRIGHT_PROXY_BYPASS=localhost,127.0.0.1
```

如果浏览器 OAuth 使用代理，建议显式绕过 localhost，避免本地回调被代理截走。

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
| `ROXYBROWSER_*` | PayPal 页面选择 RoxyBrowser 模式 |
| `GOPAY_AUTO_SIGNUP_*` | 自动注册 GoPay 钱包 |
| `REKBERINAJA_*` | GoPay 充值辅助 |
| `WHATSAPP_*`, `ANDROID_ADB_PATH` | 从 Android/ADB 读取 WhatsApp OTP |

这些配置通常包含服务商 token、手机号池、登录态或钱包数据，必须只保存在本地 `.env` 或 `data/.env`，不要提交到 Git。
