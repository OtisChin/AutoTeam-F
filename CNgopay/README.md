# CNgopay-pro

ChatGPT Plus 全自动批量订阅工具(印尼 GoPay 通道)。

> **当前版本: 1.3** — 新增 `refresh` / `linkedapps` / `profile` / `fix-failed` / `link-only` 五个运维 / 诊断命令;midtrans charge 请求头按 newpay.har 字节级对齐(加 `accept-encoding` / `priority` + 全小写);post-PIN provider-redirect + app/authorize 浏览器导航回放;允许 charge 阶段 `transaction_status=deny` 不阻断、走 payment/validate 由 GoPay 后端最终裁定。详见仓库根的 `*.cmd` / `*.sh` 一键脚本。

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

所有脚本在项目根目录直接跑。

| 命令 | 用途 |
|---|---|
| `.\codex.cmd` | VM sentinel(快,偶尔报 invalid_auth_step) |
| `.\codex.cmd 5` | 同上,串行跑 5 个 |
| `.\codex-st.cmd` | 浏览器 sentinel(稳但慢) |
| `.\codex-st.cmd 5` | 同上,串行跑 5 个 |
| `.\codex-pool.cmd 4` | **真并发批量(推荐)**,4 个独立 worker 同时跑,各自隔离 hotmail 子池 |
| `.\reg.cmd` | 批量注册 GoPay + 等 Rp1 到账 |
| `.\harvest.cmd` | 收割开 Plus + 换绑(消费 pool_tokens.txt 里的 token) |
| `.\rebind.cmd` | 单独换绑释放(不开 Plus),`-slot slot-01` 指定单个 |
| `.\status.cmd` | 看池状态汇总 |
| `.\refresh.cmd` | **强制刷新所有 slot 的 access/refresh token**(不烧 OTP / 不发短信)。token 过期或想强制轮换时跑 |
| `.\linkedapps.cmd` | **查所有 slot 在 GoPay 上已链接的商户列表**(只读),自动标记 OpenAI 命中 + 列出 link_id |
| `.\profile.cmd` | **查所有 slot 当前在 GoPay 上绑定的手机号 + 邮箱**(只读),与 state.json 比对(用于验证 rebind 是否生效) |
| `.\fix-failed.cmd` | 把"钱没扣 + token 还活"的 FAILED slot 批量回退到 WALLET_READY,可继续 harvest |
| `.\link-only.cmd` | **只跑 linking 不发 charge** 的诊断模式;跑完用 `linkedapps.cmd` 验证 link 是否真建立 |

### 典型工作流

```
.\codex-pool.cmd 4   # 并发出 4 个 ChatGPT token
.\reg.cmd             # 用 pool_numbers.txt 批量注册 GoPay,等 Rp1
.\harvest.cmd         # 4 token 配 4 钱包,开 Plus + 换绑
.\status.cmd          # 看结果
```

---

## 工具命令(只读 / 维护)

这三个命令都是只读或纯刷新,**不烧短信、不发 OTP、不动钱包余额**,用来日常运维 / 诊断。
都支持 `-slot slot-01` 只对单个 slot 操作,不带就是全部 slot。

### `.\refresh.cmd` —— 批量刷 token

把所有有 `refresh_token` 的 slot 走一次 `goto-auth/token`(grant_type=refresh_token),
拿到全新的 `access_token` + `refresh_token`(GoPay 每次刷新都会轮换 refresh)。

```
.\refresh.cmd                  # 刷所有 slot
.\refresh.cmd -slot slot-01    # 只刷一个 slot
```

跳过 EMPTY / RELEASED / 无 `refresh_token` 的 slot;失败原因写到 `slot.error`。
状态机不变,只更新 `access_token` / `refresh_token` / `error` 三字段。

### `.\linkedapps.cmd` —— 查 GoPay 已链接商户(标 OpenAI)

`GET customer.gopayapi.com/v1/linkedapps`,列出每个 slot 当前钱包关联的所有商户,
自动用 `service_name` 含 `OpenAI` / `ChatGPT`(兜底 `service_image_url`)判定 OpenAI 命中,
并打印对应的 `link_id`(以后做主动 unlink 时用)。

```
.\linkedapps.cmd                  # 查所有 slot
.\linkedapps.cmd -slot slot-01    # 只查一个
```

输出示例:

```
SLOT       PHONE            STATUS  OPENAI   LINKS
----------------------------------------------------------------------------------------------------
slot-01    +6281930860397   OK               (无任何 link)
slot-02    +6281234567890   OK      ✓        OpenAI LLC×1  [link_id=20260601c917...]
slot-03    +6281987654321   OK               Tokopedia×1, GoFood×1
slot-04    +62812xxxxx      ERR              (linkedapps 失败 (401): {...})
----------------------------------------------------------------------------------------------------
汇总: 共查 20 个 slot,  OpenAI 命中 1 个,  失败 0 个
```

ERR 是 401 时,先跑 `.\refresh.cmd` 再重跑。

### `.\profile.cmd` —— 验证当前绑定的手机号 / 邮箱

`GET api.gojekapi.com/gojek/v2/customer`,拿账号当前实际绑定的 phone + email,
跟 `state.json` 里 `full_phone` 字段比对。最常用的两个用途:

- 确认 `harvest.cmd` / `rebind.cmd` 真的把稳定号换成临时号了(EXPECTED ≠ ACTUAL = 已换出去)
- 体检 `access_token` 还活着(401 = 该跑 `refresh.cmd`)

```
.\profile.cmd                  # 查所有 slot
.\profile.cmd -slot slot-01    # 只查一个
```

输出示例:

```
SLOT       EXPECTED         ACTUAL           MATCH   EMAIL                          NOTE
--------------------------------------------------------------------------------------------------------------
slot-01    +6281930860397   +6281930860397   ✓       (空)
slot-02    +6281234567890   +66987654321     ✗                                      号已变更(rebind 已生效?)
slot-03    +62812xxxxx      ?                                                       (profile 失败 (401): {...})
--------------------------------------------------------------------------------------------------------------
汇总: 共查 20 个 slot, 失败 1 个
```

### `.\fix-failed.cmd` —— FAILED slot 批量恢复

把符合"钱没扣 + token 还活"的 FAILED slot 回退到 `WALLET_READY`,让它们能继续被 harvest。
回退条件(全部满足):

- `state == FAILED`
- 有 access_token 和 refresh_token
- `last_balance_idr >= balance_threshold`
- error 文案在白名单里(midtrans charge deny / EOF / context deadline / network reset 等)

不在白名单的 FAILED(比如 PIN setup 失败、签名错误、钱已扣但没 Plus 等)不动。

```
.\fix-failed.cmd                  # 处理所有
.\fix-failed.cmd -slot slot-02    # 处理一个
```

### `.\link-only.cmd` —— linking 诊断(不发 charge)

跑到 `validate-pin → app/authorize` 完成就停下,**不发 midtrans charge → 钱包余额不动 → token 不消费**。
跑完后用 `linkedapps.cmd` 验证:slot 上是否真的出现了 OpenAI LLC link。

主要用途:**当 harvest 总是 fraud=deny 时,排除"linking 没真建立"的可能**。
HAR 验证:linking 完成后立刻查 `linkedapps` 必能看到 OpenAI link;deny 是 charge 阶段 midtrans FDS 的判定,跟 linking 流程本身无关。

```
.\link-only.cmd                  # 测所有 WALLET_READY
.\link-only.cmd -slot slot-19    # 测一个
```

成功后 slot 状态保持 `PLUS_PAYING`(便于诊断,需手工 fix-failed 再恢复)。

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
  "cliproxyApiBaseUrl": "https://cpa.iceaix.com",
  "cliproxyApiManagementKey": "..."
}
```

---

## 数据文件

每个文件一行一条,`#` 开头是注释。

| 文件 | 内容 | 格式 |
|---|---|---|
| `pool_numbers.txt` | GoPay 稳定号(印尼,sms8 接码) | `+62xxx----https://api.sms8.net/api/record?token=xxx` |
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
                                                    │
                                                    ├─→ FAILED (支付/校验/网络失败,跳过/手工重置)
                                                    ↓
                                                PLUS_DONE
                                                    ↓
                                                REBINDING ─→ RELEASED (终态,自动重置开新一轮)
                                                            FAILED (失败,跳过/手工重置)
```

`RELEASED` 和 `FAILED` 状态会被 `.\reg.cmd` **自动重置**,用同手机号注册新一轮(全新设备指纹 + 新 GoPay 账号)。`NO_TRIAL` 会跳过,可换 token 继续收割或手工重置。

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

网络抖动(stripe/midtrans/gopay 临时不可达,或代理出口断了)。失败会落到 `FAILED`。确认钱包余额未扣后,把对应 slot 状态改回 `WALLET_READY`,跑 `.\harvest.cmd` 重试。

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

```
