# CNgopay-pro

ChatGPT Plus 全自动批量订阅工具(印尼 GoPay 通道)。

跨平台:**Windows / macOS / Linux** 都支持(Go 静态二进制)。

注册 ChatGPT free 账号 → 注册 GoPay 印尼钱包 → 等官方 Rp1 赠款 → 用 GoPay 给 ChatGPT 开通 Plus(首月免费)→ 换绑临时号释放稳定号回收。

---

## 架构

两层设计,各跑各的,通过文件对接:

```
┌─────────────────────────┐                ┌──────────────────────────┐
│ codex_register/  (Node) │                │ pool.exe  (Go)           │
│  注册 ChatGPT free      │ ──token 文件─▶ │  注册 GoPay + 开 Plus    │
│  US 代理 / 哥伦比亚号   │                │  ID 代理 / 印尼号 / JP 探  │
└─────────────────────────┘                └──────────────────────────┘
        ↓                                                ↓
   pool_tokens.txt  ◀──────── 文件对接 ────────▶  consume 后删除
```

- **Go pool**:批量注册 GoPay → 等 Rp1 → 收割开 Plus + 换绑释放稳定号
- **TS codex_register**:注册 ChatGPT free 账号 + add-email + CPA 入库,每注册成功一个 append 一行 access_token 到 `pool_tokens.txt`
- **试用探测**:codex 端 + Go pool 端双探(stripe init 看 amount_due),无试用账号自动跳过,GoPay 余额完整保留

---

## 一键命令清单

所有脚本在项目根目录直接跑。**Windows 用 `.cmd`,macOS/Linux 用 `.sh`**(Linux/Mac 第一次跑前 `chmod +x *.sh`)。

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
```

---

## 配置文件

### `config.json`(Go pool)

```jsonc
{
  "gopay_pin": "981203",
  "country_code": "+62",
  "proxy_id": "socks5://...region-ID:...",     // GoPay 走印尼节点
  "proxy_jp": "http://...region-JP:...",       // chatgpt/stripe 走日本节点(试用探测)
  "rebind_email": "123456@gmail.com",
  "hero_sms": {                                 // 换绑临时号(印尼/泰国轮询)
    "api_key": "...",
    "service": "ni",
    "max_price": 0.08,
    "countries": [{"id": 6, "code": "+62"}, {"id": 52, "code": "+66"}]
  },
  "pool": {
    "slots": 5,                                 // 一次最多跑几个 slot
    "concurrency": 5,                           // 并发数
    "balance_poll_interval_sec": 15,            // 余额轮询间隔
    "balance_threshold_idr": 1                  // Rp1 到账即视为就绪
  }
}
```

### `codex_register/config.json`(ChatGPT 注册)

```jsonc
{
  "defaultProxyUrl": "socks5://...region-US:...",  // codex 主流程走 US
  "defaultPassword": "...",
  "heroSMSCountry": 33,                            // 33=哥伦比亚(默认)
  "cliproxyApiBaseUrl": "https://your-cpa-host.example.com",
  "cliproxyApiManagementKey": "..."
}
```

---

## 数据文件

每个文件一行一条,`#` 开头是注释。

| 文件 | 内容 | 格式 |
|---|---|---|
| `pool_numbers.txt` | GoPay 稳定号(https://api.cc/,sms8 接码) | `+62xxx----https://api.sms8.net/api/record?token=xxx` |
| `pool_emails.txt` | Hotmail 卡密池(给 codex add-email 用) | `email----password----client_id----refresh_token` |
| `pool_tokens.txt` | ChatGPT access_token(codex 写入,Go pool 消费) | 每行一条 JWT |
| `hotmail_inbox.history.txt` | 已消费的 hotmail 卡密(审计,不用动) | 自动维护 |
| `runs/pool/state.json` | slot 状态持久化(id/账号/钱包/fingerprint) | 自动维护 |

---

## slot 状态机

```
EMPTY → GOPAY_REGISTERING → WALLET_WAITING → WALLET_READY
                                                    ↓
                                                PLUS_PAYING ─→ NO_TRIAL (钱包保留,可换 token)
                                                    ↓
                                                PLUS_DONE
                                                    ↓
                                                REBINDING ─→ RELEASED (终态,自动重置开新一轮)
                                                            FAILED (失败,跳过/手工重置)
```

`RELEASED` 状态会被 `.\reg.cmd` **自动重置**,用同手机号注册新一轮(全新设备指纹 + 新 GoPay 账号)。

---

## 常见错误

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

网络抖动(stripe/midtrans/gopay 临时不可达,或代理出口断了)。重试就好。把 `PLUS_PAYING` slot 状态改回 `WALLET_READY`,跑 `.\harvest.cmd` 重试。

### `ERR_SOCKS_CONNECTION_FAILED` / `ERR_INVALID_AUTH_CREDENTIALS`(playwright sentinel)

Playwright 不支持带认证的 socks5。脚本里 `SENTINEL_BROWSER_PROXY` **必须用 http 协议**(同账号同端口,只换协议头),已在 codex.cmd / codex-st.cmd 里默认设好。

---

## 试用探测设计

为什么要双探(codex + Go pool):

- **codex 端**(OAuth 完成 + CPA 入库后):用 JP 代理打 chatgpt checkout + stripe init,**无试用 → exit 2**,不写 token、消费 hotmail(已绑死)
- **Go pool 端**(harvest 时):用同一 JP 代理再探一次,**无试用 → NO_TRIAL**,GoPay 钱包不动,token 自动从池里删掉

注:同账号反复打 checkout 可能被 OAI 视为"已经走过 checkout 流程"返回不同 amount,所以两边判断偶尔不一致是正常的。

---

## 关键设计

- **设备指纹隔离**:每个 GoPay slot 一份独立 `DeviceFingerprint`(iPad 指纹 + uuid + x_m1 + x_location),全生命周期复用,不同 slot 绝不共享
- **TLS 指纹**:Go 端用 `bogdanfinn/tls-client` Chrome_146 profile;codex 端用 undici 默认(够过 chatgpt.com,但 stripe 经过日本中转代理时偶尔被 CDN 反向 RST)
- **签名**:GoPay `x-e1` HMAC + midtrans snap(byteswap),Python 与 Go 字节级一致
- **PIN 登录**:已注册账号 `default_method=goto_pin` 时走 `cvs/v1/initiate(goto_pin) → pin/tokens/nb → cvs/v1/verify`,完全照真机 HAR 路径
- **token 池消费**:harvest 成功(RELEASED)或精确无试用(NO_TRIAL)→ 从 `pool_tokens.txt` 删除该行;其他失败保留以便调试
- **hotmail 卡密消费**:codex 注册成功(无论有无试用)都消费,失败(网络/业务)不消费

---

## 编译与开发

需要 Go 1.21+ 和 Node 18+。

```
# Go pool
go build -o pool.exe ./cmd/pool

# codex_register
cd codex_register
npm install
npm run build           # 可选,bundle 后启动更快
```

---

## 文件结构

```
CNgopay-pro/
├── pool.exe                    # Go 主程序
├── config.json                 # Go pool 配置
├── codex_register/             # TS ChatGPT 注册器
│   ├── src/
│   │   ├── index.ts            # 主入口(--codex-cpa 模式)
│   │   ├── openai.ts           # OAI HTTP 协议
│   │   ├── sentinel.ts         # 反作弊 token VM 实现
│   │   ├── sentinel-browser.ts # 浏览器 sentinel(--st)
│   │   ├── probe-trial.ts      # 试用探测(JP 代理)
│   │   ├── consume-hotmail.ts  # hotmail 卡密消费
│   │   └── mail/hotmail.ts
│   └── config.json
├── cmd/pool/main.go            # Go pool 入口
├── internal/
│   ├── gopay/                  # GoPay 协议
│   │   ├── signer.go           # x-e1 签名 + 设备指纹
│   │   ├── account.go          # 注册
│   │   ├── login.go            # 登录(SMS / PIN 双路径)
│   │   ├── auth.go             # 统一鉴权入口
│   │   └── rebind.go           # 换绑释放
│   ├── charger/                # 开 Plus 流程
│   │   ├── flow.go             # checkout → stripe → midtrans → PIN → charge → verify
│   │   ├── snapsign.go         # midtrans snap 签名
│   │   └── ...
│   ├── pool/                   # 池调度
│   │   ├── pool.go             # 注册并发 + 余额轮询
│   │   └── harvest.go          # 收割
│   ├── herosms/                # hero-sms 接码(换绑用)
│   ├── sms8/                   # sms8.net 接码(注册/linking 用)
│   ├── httpx/                  # tls-client 封装
│   └── state/                  # slot 状态机 + 落盘
├── runs/pool/state.json        # 持久化状态
├── pool_numbers.txt            # GoPay 稳定号
├── pool_emails.txt             # Hotmail 卡密
├── pool_tokens.txt             # ChatGPT token 池
└── *.cmd / codex-pool.ps1      # 一键脚本
```
