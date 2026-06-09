# 从零开始部署

## 前置要求

- Python 3.10 或更高版本。
- 推荐安装 `uv`。
- 需要浏览器自动化时安装 Playwright Chromium。
- 如果使用 Docker，需要 Docker Compose。

## 本地部署

Windows 推荐：

```powershell
deploy-local.cmd
```

指定端口：

```powershell
deploy-local.cmd -Port 8899
```

macOS / Linux：

```bash
bash setup.sh
```

或者手动：

```bash
uv sync
uv run playwright install chromium
```

## 配置

复制配置模板：

```bash
cp .env.example .env
```

至少填写：

```env
MAIL_PROVIDER=cloudflare_temp_email
CLOUDFLARE_TEMP_EMAIL_BASE_URL=https://example.com/api
CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD=your_password
CLOUDFLARE_TEMP_EMAIL_DOMAIN=@example.com
CPA_URL=http://127.0.0.1:8317
CPA_KEY=your_key
API_KEY=change-me
```

更多配置见 [配置说明](configuration.md)。

## 启动

Web 面板和 API：

```bash
uv run autotoken api
```

指定端口：

```bash
uv run autotoken api --port 8899
```

命令行轮转：

```bash
uv run autotoken rotate
```

打开：

```text
http://127.0.0.1:8787
```

如果设置了 `API_KEY`，请求 `/api/*` 时需要携带：

```text
Authorization: Bearer <API_KEY>
```

## 首次检查

1. 访问 Web 面板，确认配置状态正常。
2. 执行一次账号同步，确认本地账号池可读写。
3. 执行一次 CPA 列表读取，确认 `CPA_URL` 和 `CPA_KEY` 正确。
4. 注册或导入一个测试账号，确认 Codex OAuth 认证文件可以生成。

## 常用命令

| 命令 | 说明 |
|------|------|
| `uv run autotoken api` | 启动 Web/API |
| `uv run autotoken rotate` | 执行轮转 |
| `uv run autotoken check` | 检查账号和额度 |
| `uv run autotoken reconcile` | 对账 workspace 与本地状态 |
| `uv run autotoken sync-cpa` | 同步 active 认证到 CPA |

旧的兼容命令仍然保留，但新脚本和文档应统一使用 `autotoken`。

## 数据目录

以下文件属于本地运行数据，已经被 Git 忽略：

| 路径 | 说明 |
|------|------|
| `.env` | 本地配置和密钥 |
| `data/` | SQLite、邮箱池和其他持久化数据 |
| `auths/` | Codex 认证文件 |
| `accounts.json`, `state.json` | 本地状态 |
| `logs/`, `outputs/`, `screenshots/` | 调试产物 |

不要把这些文件提交到 Git。已经泄露过的 token 或账号凭据需要轮换。
