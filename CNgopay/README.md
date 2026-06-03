# CNgopay-pro 1.3

ChatGPT Plus 全自动批量订阅工具(印尼 GoPay 通道)。

跨平台:**Windows / macOS / Linux** 都支持(Go 静态二进制)。

注册 ChatGPT free 账号 → 注册 GoPay 印尼钱包 → 等官方 Rp1 赠款 → 用 GoPay 给 ChatGPT 开通 Plus(首月免费)→ 换绑临时号释放稳定号回收。

---

## 1.3 更新内容

相比 1.2:

- **新增 5 个运维 / 诊断命令**:`refresh` / `linkedapps` / `profile` / `fix-failed` / `link-only`
- **midtrans charge 请求头按 newpay.har 字节级对齐**:加 `accept-encoding` / `priority`,所有 header 改成全小写(HTTP/2 真实浏览器行为)
- **post-PIN 浏览器导航回放**:`provider-redirect` + `app/authorize` 两条 GET 在 validate-pin 前后按真实顺序补齐
- **charge fraud=deny 不再立即阻断**:HTTP 200 + `transaction_status=deny` 时 warn 后继续走 `payment/validate`,由 GoPay 后端最终裁定
- **harvest 失败的 slot 走 `fix-failed` 可批量恢复**(钱没扣的 FAILED → WALLET_READY,token 不消费)
- **billing / device 指纹随机化增强**:每个 slot 用独立 hosted_checkout merchant_integration 字段;30+ 美国城市/州/邮编池
- **TH 优先**:换绑国家轮询从 ID→TH 改为 TH→ID(可在 `config.json:hero_sms.countries` 调整)
- **代理路由可调**:charger 内部 client(stripe/midtrans/gopayapi)默认全走 `proxy_jp`(单一 rotating 出口比 ID/JP 分流稳)

---

## 架构

两层设计,各跑各的,通过文件对接:

```
┌─────────────────────────┐                ┌──────────────────────────┐
│ codex_register/  (Node) │                │ pool 二进制  (Go)        │
│  注册 ChatGPT free      │ ──token 文件─▶ │  注册 GoPay + 开 Plus    │
└─────────────────────────┘                └──────────────────────────┘
        ↓                                                ↓
   pool_tokens.txt  ◀──────── 文件对接 ────────▶  consume 后删除
```

- **Go pool**:批量注册 GoPay → 等 Rp1 → 收割开 Plus + 换绑释放稳定号
- **TS codex_register**:注册 ChatGPT free 账号 + add-email + CPA 入库,append access_token 到 `pool_tokens.txt`
- **试用探测**:codex 端 + Go pool 端双探(stripe init 看 amount_due),无试用账号自动跳过,GoPay 余额完整保留

---

## 一键命令清单

所有脚本在项目根目录直接跑。**Windows 用 `.cmd`,macOS/Linux 用 `.sh`**(Linux/Mac 第一次跑前 `chmod +x *.sh`)。

### 主流程

| 功能 | Windows | macOS/Linux |
|---|---|---|
| 注册 ChatGPT(VM 快) | `.\codex.cmd` | `./codex.sh` |
| 注册 ChatGPT(浏览器稳) | `.\codex-st.cmd` | `./codex-st.sh` |
| 串行 N 个 | `.\codex.cmd 5` | `./codex.sh 5` |
| **真并发批量** | `.\codex-pool.cmd 4` | (Windows 专属;macOS 用 GNU parallel 或 tmux) |
| 注册 GoPay + 等 Rp1 | `.\reg.cmd` | `./reg.sh` |
| 收割开 Plus + 换绑 | `.\harvest.cmd` | `./harvest.sh` |
| 单独换绑 | `.\rebind.cmd` | `./rebind.sh` |
| 看池状态 | `.\status.cmd` | `./status.sh` |

### 1.3 新增运维 / 诊断

| 命令 | Windows | macOS/Linux | 用途 |
|---|---|---|---|
| 强制刷 token | `.\refresh.cmd` | `./refresh.sh` | 用 refresh_token 刷一遍所有 slot 的 access/refresh(不烧 OTP / 不发短信) |
| 查 GoPay 已链接商户 | `.\linkedapps.cmd` | `./linkedapps.sh` | 只读;识别 OpenAI 命中 + 列出 link_id |
| 查当前绑定 phone/email | `.\profile.cmd` | `./profile.sh` | 只读;与 state.json 比对验证 rebind |
| FAILED 批量恢复 | `.\fix-failed.cmd` | `./fix-failed.sh` | "钱没扣 + token 还活"的 FAILED → WALLET_READY |
| 只 linking 不 charge | `.\link-only.cmd` | `./link-only.sh` | 诊断模式;跑完用 linkedapps 验证 link 是否真建立 |

所有诊断命令支持 `-slot slot-XX` 只对单个 slot 操作。

### 二进制文件(根据系统选)

| 系统 | 文件 |
|---|---|
| Windows x64 | `pool.exe` |
| Linux x64 | `pool-linux-x64` |
| macOS Intel | `pool-mac-intel` |
| macOS Apple Silicon (M1/M2/M3) | `pool-mac-arm64` |

**Linux/macOS** 用 `pool.sh` 包装,自动选对应架构。第一次用要 `chmod +x pool.sh pool-* *.sh`。

### 典型工作流

```
.\codex-pool.cmd 4   # 并发出 4 个 ChatGPT token
.\reg.cmd             # 用 pool_numbers.txt 批量注册 GoPay,等 Rp1
.\harvest.cmd         # 4 token 配 4 钱包,开 Plus + 换绑
.\status.cmd          # 看结果

# 当 harvest 失败比较多时:
.\fix-failed.cmd      # 钱没扣的 FAILED 拉回 WALLET_READY
.\harvest.cmd         # 再来一轮

# 诊断:
.\linkedapps.cmd      # 看每个 slot 当前 GoPay 上有没有 OpenAI link
.\profile.cmd         # 看绑定的真实手机号(检查 rebind)
.\link-only.cmd       # 只测 linking 不发 charge
```

---

## 配置文件

### `config.json`(Go pool)

```jsonc
{
  "gopay_pin": "981203",
  "country_code": "+62",
  "proxy_id": "socks5://...region-ID:...",     // GoPay 走印尼节点(注册流程)
  "proxy_jp": "http://...region-JP:...",       // chatgpt/stripe + 现版 midtrans/gopayapi 都走 JP
  "rebind_email": "123456@gmail.com",
  "hero_sms": {                                 // 换绑临时号(泰国优先)
    "api_key": "...",
    "service": "ni",
    "max_price": 0.08,
    "countries": [
      {"id": 52, "code": "+66", "name": "TH"},
      {"id": 6,  "code": "+62", "name": "ID"}
    ]
  },
  "pool": {
    "slots": 5,
    "concurrency": 5,
    "balance_poll_interval_sec": 15,
    "balance_threshold_idr": 1
  }
}
```

### `codex_register/config.json`(ChatGPT 注册)

```jsonc
{
  "defaultProxyUrl": "socks5://...region-US:...",
  "defaultPassword": "...",
  "heroSMSCountry": 33,
  "cliproxyApiBaseUrl": "https://your-cpa-host.example.com",
  "cliproxyApiManagementKey": "..."
}
```

---

## 数据文件

每个文件一行一条,`#` 开头是注释。

| 文件 | 内容 | 格式 |
|---|---|---|
| `pool_numbers.txt` | GoPay 稳定号(sms8 接码) | `+62xxx----https://api.sms8.net/api/record?token=xxx` |
| `pool_emails.txt` | Hotmail 卡密池 | `email----password----client_id----refresh_token` |
| `pool_tokens.txt` | ChatGPT access_token | 每行一条 JWT |
| `hotmail_inbox.history.txt` | 已消费的 hotmail 卡密(自动维护) | |
| `runs/pool/state.json` | slot 状态持久化(自动维护) | |

---

## slot 状态机

```
EMPTY → GOPAY_REGISTERING → WALLET_WAITING → WALLET_READY
                                                    ↓
                                                PLUS_PAYING ─→ NO_TRIAL (钱包保留,可换 token)
                                                    │
                                                    ├─→ FAILED (失败 → fix-failed 可回退)
                                                    ↓
                                                PLUS_DONE
                                                    ↓
                                                REBINDING ─→ RELEASED (终态,reg.cmd 自动重置开新一轮)
```

`RELEASED` 状态会被 `.\reg.cmd` **自动重置**,用同手机号注册新一轮(全新设备指纹 + 新 GoPay 账号)。`NO_TRIAL` 会跳过,可换 token 继续收割或手工重置。`FAILED` 跑 `.\fix-failed.cmd` 可批量恢复(钱没扣的)。

---

## 常见错误

### `midtrans charge denied: status=deny fraud=deny code=202`

midtrans 反作弊系统(FDS)对当前 charge 的判定。1.3 已经把请求字节级对齐 newpay.har 的真实浏览器流量,但部分钱包/号段仍可能被 FDS 评分拒绝(常见于历史频繁失败的钱包)。

处理:
- 失败的 slot 已自动落 `FAILED`,**钱包未受损,token 未消费**
- 跑 `.\fix-failed.cmd` 拉回 WALLET_READY → 再 `.\harvest.cmd` 多试几轮
- 经过几轮后还是 deny 的钱包可以换号(`rebind` → `reg` 重注册)

### `payment/validate failed after retries: 404 Payment details not found`

charge 这一步 midtrans 已 fraud=deny,但代码继续走了 payment/validate。GoPay 后端认不到这个 charge_ref,所以 404。归类为可恢复错误,`fix-failed` 自动认领。

### `Please update to the latest official app version` (401)

GoPay 后端识别该号是 PIN 优先登录(`default_method=goto_pin`),普通 SMS 路径走不通。**已自动支持 PIN 路径**(用 `gopay_pin` 配置项的 PIN 直接登录)。

### `auth:error:ratelimited` (限流 60 分钟)

该号在 GoPay 后端被限流。**等 1 小时**或**用别的号代替**。把 `pool_numbers.txt` 里那行注释掉(`#` 开头)。

### `invalid_auth_step` (codex 端)

OAI 认为该手机号已注册过 → 跳到 `/log-in/password`。代码已加**早期识别**,自动 markAsFailed + 换号。

### `chatgpt checkout 400: User is already paid`

该 ChatGPT 账号已经是 Plus,不能再开。换新 token。

### `stripe init amount=非0 idr` → NO_TRIAL

该 ChatGPT 账号无免费试用资格(可能用过、或被风控)。GoPay 钱包**完整保留**,把 slot 状态改回 `WALLET_READY`,用下一个 token 重试。

### `EOF` / `context deadline exceeded`

网络抖动(stripe/midtrans/gopay 临时不可达,或代理出口断了)。归 `fix-failed` 白名单,自动恢复。

### `ERR_SOCKS_CONNECTION_FAILED` / `ERR_INVALID_AUTH_CREDENTIALS`(playwright sentinel)

Playwright 不支持带认证的 socks5。脚本里 `SENTINEL_BROWSER_PROXY` **必须用 http 协议**(同账号同端口,只换协议头),已在 `codex.cmd / codex-st.cmd` 里默认设好。

---

## 试用探测设计

为什么要双探(codex + Go pool):

- **codex 端**(OAuth 完成 + CPA 入库后):用 JP 代理打 chatgpt checkout + stripe init,**无试用 → exit 2**,不写 token、消费 hotmail(已绑死)
- **Go pool 端**(harvest 时):用同一 JP 代理再探一次,**无试用 → NO_TRIAL**,GoPay 钱包不动,token 自动从池里删掉

注:同账号反复打 checkout 可能被 OAI 视为"已经走过 checkout 流程"返回不同 amount,所以两边判断偶尔不一致是正常的。

---

## 文件清单

```
.
├── pool.exe                    # Windows 二进制
├── pool-linux-x64              # Linux 二进制
├── pool-mac-intel              # macOS Intel 二进制
├── pool-mac-arm64              # macOS Apple Silicon 二进制
├── pool.sh                     # macOS/Linux 自动选架构
├── setup.sh                    # macOS/Linux 一键赋权
├── config.json                 # 主配置(填代理 / hero / cpa)
├── config.example.json         # 配置模板
├── codex_register/             # ChatGPT 注册器(Node)
│   ├── src/                    # 源码
│   ├── sdk.js                  # OpenAI 反作弊 SDK
│   ├── package.json
│   └── config.json             # codex 配置(填代理 / hero / cpa)
├── pool_numbers.txt            # GoPay 稳定号池
├── pool_emails.txt             # Hotmail 卡密池
├── pool_tokens.txt             # ChatGPT token 池
├── codex.cmd / codex.sh        # 注册 ChatGPT(VM 模式)
├── codex-st.cmd / codex-st.sh  # 注册 ChatGPT(浏览器模式)
├── codex-pool.cmd              # 真并发批量(Windows)
├── codex-pool.ps1              # 并发实现(Windows)
├── reg.cmd / reg.sh            # 注册 GoPay
├── harvest.cmd / harvest.sh    # 开 Plus + 换绑
├── rebind.cmd / rebind.sh      # 单独换绑
├── status.cmd / status.sh      # 看池状态
├── refresh.cmd / refresh.sh           # 1.3 — 强制刷 token
├── linkedapps.cmd / linkedapps.sh     # 1.3 — 查 GoPay 已链接商户
├── profile.cmd / profile.sh           # 1.3 — 查当前绑定的 phone/email
├── fix-failed.cmd / fix-failed.sh     # 1.3 — FAILED 批量恢复
└── link-only.cmd / link-only.sh       # 1.3 — 只跑 linking 不发 charge(诊断)
```

`hotmail_inbox.history.txt` 和 `runs/pool/state.json` 是运行时自动生成,不用预先存在。
