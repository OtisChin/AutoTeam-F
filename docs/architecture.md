# 工作原理

## 总体目标

AutoToken-F 用来维护 ChatGPT Team 账号池、认证文件和 CPA 同步状态。核心目标是：

1. 让 Team 席位数量接近目标值。
2. 在账号额度不足或认证失效时及时轮转。
3. 将可用认证文件同步到 CPA，并支持从 CPA 反向恢复。
4. 将注册、OAuth、支付绑定和账号清理这些高风险流程拆到清晰模块中维护。

## 目录结构

运行时代码以 `src/autotoken/` 为唯一 canonical 包。根层 `.py` 文件除 `__init__.py` 和 `__main__.py` 外，都是兼容 wrapper；真实实现按职责放在子目录中：

| 目录 | 职责 |
|------|------|
| `interfaces/` | CLI、历史 manager 入口、FastAPI app 组合 |
| `api_routes/` | HTTP 路由分组 |
| `auth/` | Codex OAuth、协议注册、邀请注册、手动账号导入 |
| `core/` | 路径、文本 IO、环境兼容、浏览器指纹、取消信号等基础能力 |
| `settings/` | 静态配置、运行时配置、管理员状态、首次配置向导 |
| `storage/` | 账号池、认证文件、SQLite、失败记录持久化 |
| `payments/` | 绑卡、GoPay、WhatsApp OTP，以及 PayPal / iDEAL / Pix / UPI / Kakao / MoMo 等支付页提链流程 |
| `integrations/` | ChatGPT API、CPA、RoxyBrowser、代理桥、Rekberinaja、导入导出转换 |
| `services/` | 可复用业务决策和任务运行时逻辑 |
| `mail/` | 临时邮箱与账号池邮箱 provider |
| `commerce/` | 交易和库存类辅助逻辑 |
| `_protocol_register/` | 纯协议注册的底层实现和 JS 指纹脚本 |
| `oauth_helper_extension/` | OAuth 本地回调辅助扩展 |
| `web/dist/` | 前端生产构建产物，发布包需要但不进入 Git |

旧包名只保留最小兼容入口，便于历史脚本在迁移期继续启动；新代码和文档应统一使用 canonical 包与 `autotoken` 命令。

## 轮转流程

```text
同步 Team 实际状态
        ↓
检查 active 账号额度和认证状态
        ↓
额度不足或认证失效 → 标记 exhausted/auth_invalid
        ↓
按策略移出 Team 或等待重试
        ↓
优先复用 standby 账号
        ↓
不足时注册新号并执行 Codex OAuth
        ↓
同步 active 认证文件到 CPA
```

## 账号状态

| 状态 | 含义 |
|------|------|
| `active` | 当前在 Team 中，且本地认为可用 |
| `exhausted` | 当前在 Team 中，但额度不足，等待移出或复核 |
| `standby` | 已不在当前轮转席位中，后续可复用 |
| `pending` | 注册、创建或 OAuth 流程尚未完成 |
| `personal` | 已转为个人号 Codex OAuth，不再参与 Team 轮转 |
| `auth_invalid` | 认证文件 token 不可用，等待对账、重登或清理 |
| `orphan` | workspace 仍占席，但本地认证文件缺失 |

## 同步模型

| 动作 | 方向 | 用途 |
|------|------|------|
| 同步账号 | Team / `auths/` → `accounts.json` 或 SQLite | 修复本地账号池记录 |
| 同步 CPA | 本地 active → CPA | 上传可用认证文件 |
| 从 CPA 同步 | CPA → 本地 | 恢复本地缺失认证文件 |
| 对账 | Team API ↔ 本地状态 | 清理 ghost、orphan、错位席位 |

## 支付页状态模型

支付页路由会把账号资格与提链结果分开持久化到 JSON 状态文件。以越南 MoMo 为例：

- `pending`：未提链
- `eligible`：检测到 `momo` 支付方式
- `ineligible`：未检测到 `momo`
- `running`：提链中
- `failed`：资格通过但后续提链失败
- `success`：已提链
- `paid`：账号已支付

前端页面参考对应渠道的独立组件展示账号池、任务日志、最近任务结果和链接管理表；后端路由负责资格检测、批量任务编排、状态写回和链接去重持久化。

## 运行数据边界

以下路径是本地运行数据或可再生成产物，不应进入 Git：

| 路径 | 说明 |
|------|------|
| `.env*` | 本地配置和密钥 |
| `accounts.json`, `state.json`, `runtime_config.json` | 本地运行状态 |
| `auths/`, `auth_state/`, `data/` | 认证文件和持久化数据 |
| `logs/`, `outputs/`, `screenshots/` | 调试输出 |
| `web/node_modules/` | 前端依赖 |
| `src/autotoken/web/dist/` | 本地 Web 构建产物 |
| `dist/` | Python 构建产物 |

发布前需要确认 `git ls-files` 不包含上述运行数据，并确认 sdist/wheel 不包含本地密钥、日志、账号池或生成依赖。
