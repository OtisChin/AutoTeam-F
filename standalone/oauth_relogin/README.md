# OAuth Relogin Standalone Module

这是从当前项目复制/抽取出来的**脱敏独立版 OAuth 补登录完整流程包**。它不复制账号数据、auth 文件、日志、代理池或 `.env`，默认端点均为占位值，搬到目标项目后只需要改配置。

## 文件

- `oauth_relogin.py`：核心 Python 模块
- `__main__.py`：CLI
- `oauth_helper_extension/`：浏览器辅助扩展，负责填邮箱/密码/手机号/OTP 并回传本地 helper 事件
- `.env.example`：配置模板

## 完整浏览器补登录流程

```python
from standalone.oauth_relogin import JsonPhonePoolProvider, run_browser_oauth_relogin_flow

phone_pool = JsonPhonePoolProvider("data/phone-pool.json")
phone_pool.import_phones("+12025550111----https://sms.example/inbox/1")

result = run_browser_oauth_relogin_flow(
    email="user@example.com",
    password="your-password",
    output_dir="data/oauth-output",
    sms_provider=phone_pool,
    phone_code_provider=lambda phone_item: "123456",
)
```

成功后会写：

- `data/oauth-output/auths/oauth-user@example.com.json`
- `data/oauth-output/phone-bindings.json`
- `data/phone-pool.json` 中该号码的绑定计数和绑定邮箱

`run_browser_oauth_relogin_flow` 会启动：

- 本地 OAuth callback server
- 本地 browser helper state/event server
- Playwright Chromium + helper extension（Playwright 不可用时退回系统浏览器）
- 接码供应商 adapter
- token exchange
- JSON auth/phone binding 落盘

## 纯协议补登录

如果目标项目已经保存了可复用 `auth_session` / cookie：

```python
from standalone.oauth_relogin import OAuthConfig, oauth_from_auth_session

bundle = oauth_from_auth_session(
    saved_auth_session,
    config=OAuthConfig.from_env(),
    email="user@example.com",
    proxy_url=None,
)
```

## 接码供应商配置

```python
from standalone.oauth_relogin import build_phone_sms_config_report, load_phone_sms_provider_configs

configs = load_phone_sms_provider_configs()
report = build_phone_sms_config_report(configs)
```

`report` 可直接给 UI/API 使用，密钥和 CDK 不会明文输出。

支持的 provider：

| provider | adapter | 能力 |
| --- | --- | --- |
| `phone_pool` | `JsonPhonePoolProvider` | JSON 手机号池导入、预约、OTP 注入、绑定计数 |
| `hero_sms` | `HandlerApiSmsProvider` | `getNumber` / `getStatus` / `setStatus=6/8` |
| `smsbower` | `HandlerApiSmsProvider` | `getNumber` / `getStatus` / `setStatus=6/8` |
| `smscloud` | `SMSCloudSmsProvider` | `/flexible` 取号、`/sync` 取码、`/finish`、`/cancel` |
| `oasis` | `CdkSmsProvider` | CDK 取号、轮询短信、JSONL 映射记录 |
| `tujie` | `CdkSmsProvider` | CDK 取号、轮询短信、取消、JSONL 映射记录 |

创建 adapter：

```python
from standalone.oauth_relogin import create_sms_provider

sms_provider = create_sms_provider("smscloud")
```

## CLI

查看脱敏配置：

```bash
python -m standalone.oauth_relogin config
```

导入 JSON 手机号池：

```bash
python -m standalone.oauth_relogin import-phones \
  --phone-pool data/oauth-phone-pool.json \
  --text "+12025550111----https://sms.example/inbox/1"
```

跑浏览器补登录：

```bash
python -m standalone.oauth_relogin login \
  --email user@example.com \
  --password "your-password" \
  --provider phone_pool \
  --phone-pool data/oauth-phone-pool.json \
  --phone-code 123456 \
  --output-dir data/oauth-output
```

## 已内置

- OAuth 配置读取
- PKCE / authorize URL / callback 解析 / token exchange
- auth_session 协议 OAuth runner
- 浏览器 helper extension
- 本地 helper server
- 本地 OAuth callback server
- Browser OAuth runner
- `phone_pool` / `hero_sms` / `smsbower` / `smscloud` / `oasis` / `tujie` 接码 adapter
- token JSON 落盘
- 手机号绑定记录 JSON 落盘
- 手机号池绑定计数/预约/释放

## 脱敏说明

- 默认 OAuth 域名是 `auth.example.com`
- 默认 `client_id` 是 `REPLACE_WITH_OAUTH_CLIENT_ID`
- helper 扩展使用 `oauth_relogin_*` 配置键，不包含原项目名称
- 不复制 `.env`、账号数据、auth 文件、日志、代理池或任何运行态数据

## 目标项目需要替换

- 真实 OAuth provider 的 `client_id` / `auth_url` / `token_url` / `redirect_uri`
- 真实接码商 API base URL 和密钥
- 账号池状态回写（如果目标项目需要账号池）
- 代理池/代理 API（如果目标项目需要）
- 如目标页面 DOM 与 helper extension 选择器不一致，需要调整 `oauth_helper_extension/content.js`
