# Docker 部署

## 快速启动

```bash
git clone https://github.com/ZRainbow1275/AutoToken-F.git
cd AutoToken-F
mkdir -p data
cp .env.example data/.env
docker compose up -d
```

启动后访问：

```text
http://127.0.0.1:8787
```

## 配置文件

Docker Compose 将本地 `./data` 挂载到容器 `/app/data`。建议只在 `data/.env` 中保存配置：

```env
MAIL_PROVIDER=cloudflare_temp_email
CLOUDFLARE_TEMP_EMAIL_BASE_URL=https://example.com/api
CLOUDFLARE_TEMP_EMAIL_ADMIN_PASSWORD=your_password
CLOUDFLARE_TEMP_EMAIL_DOMAIN=@example.com
CPA_URL=http://host.docker.internal:8317
CPA_KEY=your_key
API_KEY=change-me
```

Linux 上如果容器不能解析 `host.docker.internal`，可以改成宿主机网关 IP，或在 compose 中添加 `extra_hosts`。

## 常用命令

```bash
docker compose up -d
docker compose logs -f
docker compose restart
docker compose down
```

进入容器：

```bash
docker compose exec autotoken bash
```

执行 CLI：

```bash
docker compose exec autotoken uv run autotoken check
docker compose exec autotoken uv run autotoken reconcile
```

## 数据持久化

`data/` 中会保存运行数据和本地配置，包括：

| 路径 | 说明 |
|------|------|
| `data/.env` | 容器内配置 |
| `data/*.sqlite3` | SQLite 数据库 |
| `data/auths/` | 认证文件 |
| `data/screenshots/` | 浏览器调试截图 |
| `data/outlook_accounts.txt` | Outlook 账号池 |
| `data/luckmail_accounts.txt` | LuckMail 账号池 |

这些文件包含敏感信息，应只保存在部署机器上。

## 构建上下文

`.dockerignore` 已排除本地密钥、日志、输出、账号池、`node_modules` 和本地构建产物。构建镜像前仍建议检查：

```bash
git status --short
git ls-files
```

确认没有将 `.env`、账号池、token、日志或认证文件加入 Git。

## 重新构建

依赖或前端代码变更后：

```bash
docker compose build --no-cache
docker compose up -d
```

Dockerfile 会在镜像构建过程中执行 `npm ci && npm run build`，前端产物写入 `src/autotoken/web/dist/`。
