---
title: Auto Bind 实现任务拆解
type: feat
status: active
date: 2026-04-28
origin: docs/auto_bind_plan.md
---

# Auto Bind 实现任务拆解

## Overview

基于现有 `POST /api/bind/link`、后台任务框架、卡池和账号池，补齐“账号 -> checkout_link -> 绑卡执行 -> 结果回写”闭环。实现目标是先交付一个可控、可审计、任务级代理隔离的 v1 闭环，不在第一版内引入激进的自动重试、代理轮换或复杂验证码黑盒处理。

## Problem Frame

当前仓库已经具备四块基础能力：

- 账号生产与 `auth_session` 保存
- 支付链接生成
- 卡池持久化
- 接码接口拉取

但还缺少真正把这些能力串成一次“绑卡任务”的执行层：没有卡分配调度、没有任务级代理、没有 Playwright 绑卡执行器、没有结构化结果回写，也没有持久化审计记录。`docs/auto_bind_plan.md` 已经给出方向，这份计划把它落到当前仓库的模块、接口和测试任务上。

## Requirements Trace

- R1. 增加后台绑卡任务入口，复用现有 `_start_task` / `_tasks` / `_playwright_lock` 体系。
- R2. 每次绑卡任务都能显式绑定代理，并在整个会话内固定使用同一出口，不修改全局 `.env`。
- R3. 卡池支持 `binding` / `failed` 状态和绑定审计字段，避免同一张卡被重复分配。
- R4. 新增执行器模块，负责打开 checkout、填卡、提交、截图和结构化结果判定。
- R5. 任务结束后，把结果回写到卡池、账号池和持久化审计文件。
- R6. 前端在现有 `BindCard.vue` 基础上提供“开始绑卡”面板，并能轮询任务状态。
- R7. 为 API、状态流、执行器结果分类补齐自动化测试，并保留可人工验收的浏览器闭环。

## Scope Boundaries

- 不做失败后自动切 IP 重试。
- 不做同卡跨账号高频轮换。
- 不引入数据库，继续使用现有 JSON 持久化模式。
- 不在 v1 内实现复杂 3DS/风控挑战自动化。

### Deferred to Separate Tasks

- 自动短信轮询与验证码回填。
- 代理池健康检查与自动挑选逻辑。
- 审计记录的前端查询页面。

## Context & Research

### Relevant Code and Patterns

- `src/autoteam/api.py`
  - 已有 `POST /api/bind/link`
  - 已有 `_start_task()`、`get_task()`、`get_tasks()`、`post_task_cancel()`
  - 现有任务接口已经足够复用，不需要为绑卡任务额外发明第二套调度器
- `src/autoteam/config.py`
  - `get_playwright_launch_options()` 目前只读全局 `PLAYWRIGHT_PROXY_URL`
  - 适合扩成“默认读全局配置，也允许任务传 override”的接口
- `src/autoteam/chatgpt_api.py`
  - `_launch_browser()` 统一承接 Playwright 启动
  - `_wait_for_cloudflare()` 可直接复用
- `src/autoteam/card_pool.py`
  - 已有卡池 JSON 持久化、`used_by` / `used_at` 字段和 `meta`
  - 适合扩展为显式的绑定状态机
- `src/autoteam/accounts.py`
  - 已有账号元数据持久化
  - 适合补写最近一次绑卡结果字段
- `web/src/components/BindCard.vue`
  - 已支持从号池提取 token 并生成 checkout link
  - 最适合作为“开始绑卡”面板入口
- `web/src/components/BindCardPool.vue`
  - 已有卡状态展示、详情面板和短信拉取
  - 需要同步扩展 `binding` / `failed` 状态显示
- `src/autoteam/register_failures.py`
  - 已有“JSON 文件 + 锁 + 最近 N 条”的持久化审计模式
  - 可直接复用到绑卡审计

### Institutional Learnings

- 当前仓库未发现可复用的 `docs/solutions/` 经验文档。

### External References

- 本次规划不依赖额外外部资料。仓库内已经有足够的本地模式可跟随。

## Key Technical Decisions

- 绑卡任务复用现有 `/api/tasks` 基础设施，不新增第二套任务系统。
- 绑卡详情查询复用通用 `GET /api/tasks/{task_id}`，不额外新增 `/api/tasks/bind-card/{task_id}`。
- `checkout_url` 由现有“生成支付链接”流程提供，v1 的绑卡任务不在后台重复生成支付链接。
- Playwright 代理采用“任务级 override，默认回退全局配置”的方式实现，不在运行时改写环境变量。
- 卡状态流采用 `unused -> binding -> used|failed|unused`，其中“是否回退到 `unused`”由失败阶段决定。
- 审计记录单独持久化到文件，避免内存 `_tasks` 被裁剪后丢失历史。
- `manual_confirm` 作为 v1 主路径保留：浏览器打开后允许人工介入完成确认，任务只负责等待结果和收口回写。

## Open Questions

### Resolved During Planning

- 是否需要新增专用任务状态查询接口：不需要，复用 `GET /api/tasks/{task_id}` 即可。
- 是否需要第一版就做短信自动回填：不需要，列为后续任务。
- 是否需要先上数据库：不需要，沿用 JSON 文件并补锁与审计字段即可。

### Deferred to Implementation

- checkout 页面在 `custom` 与 `hosted` 模式下的精确成功信号，需要在真实页面上校准。
- 部分失败类型应回退到 `unused` 还是固化为 `failed`，最终要按“是否已经发起有效支付提交”定规则。
- 截图保留策略与文件命名规则，需要在实现时根据现有 `data/` 目录布局确定。

## Implementation Units

- [ ] **Unit 1: 绑卡任务接口与前置校验**

**Goal:** 增加 `POST /api/tasks/bind-card`，把绑卡能力纳入现有后台任务体系。

**Requirements:** R1, R5, R6

**Dependencies:** None

**Files:**
- Modify: `src/autoteam/api.py`
- Modify: `web/src/api.js`
- Test: `tests/unit/test_bind_task_api.py`

**Approach:**
- 在 `src/autoteam/api.py` 中新增 `BindCardTaskParams`。
- 新增 `POST /api/tasks/bind-card`，参数至少包含 `email`、`card_item_id`、`checkout_url`、`proxy_url`、`proxy_label`、`manual_confirm`。
- 在启动任务前做同步校验：账号存在、账号具备可用 `auth_session_file`、卡项存在且状态允许分配、`checkout_url` 非空。
- 任务命令名统一为 `bind-card`，结果继续复用通用 `GET /api/tasks/{task_id}` 查询。

**Patterns to follow:**
- `src/autoteam/api.py` 中现有的 `POST /api/tasks/check`
- `src/autoteam/api.py` 中现有的 `_start_task()` / `get_task()`

**Test scenarios:**
- Happy path: 传入合法参数时返回 `202`，结果中包含 `task_id`、`command=bind-card`、原始 `params`。
- Error path: `email` 不存在时返回 `404`。
- Error path: `card_item_id` 不存在或卡状态不是 `unused` 时返回 `400` 或 `404`。
- Error path: `checkout_url` 为空时返回 `400`。
- Integration: 新任务启动后可被 `GET /api/tasks/{task_id}` 查询到。

**Verification:**
- 前端可以像现有其他后台任务一样启动绑卡任务并拿到 `task_id`。

- [ ] **Unit 2: 任务级代理注入到 Playwright**

**Goal:** 让绑卡任务能在不污染全局配置的前提下使用独立代理。

**Requirements:** R2

**Dependencies:** Unit 1

**Files:**
- Modify: `src/autoteam/config.py`
- Modify: `src/autoteam/chatgpt_api.py`
- Test: `tests/unit/test_bind_executor.py`

**Approach:**
- 把 `get_playwright_launch_options()` 扩展为接受可选的 `proxy_url` / `proxy_bypass` override。
- 把 `ChatGPTTeamAPI._launch_browser()` 扩展为接受代理参数，并把它透传到 Playwright 启动层。
- 保持所有现有调用点兼容：不传 override 时继续沿用全局 `PLAYWRIGHT_PROXY_URL`。
- 禁止在任务执行期间动态写 `.env` 或修改模块级配置。

**Patterns to follow:**
- `src/autoteam/config.py` 中现有的 `_parse_proxy_url()`
- `src/autoteam/chatgpt_api.py` 中现有的 `_launch_browser()`

**Test scenarios:**
- Happy path: 传入任务级 `proxy_url` 时，返回的 launch options 使用任务代理而不是全局代理。
- Edge case: 未传任务代理时，保持现有全局配置行为不变。
- Edge case: 带用户名密码的代理 URL 能被正确拆分到 `server` / `username` / `password`。
- Integration: 绑卡执行器传入代理参数后，`ChatGPTTeamAPI` 能按该参数启动浏览器。

**Verification:**
- 同一进程内其他任务仍使用全局代理配置，而绑卡任务使用自己的代理配置。

- [ ] **Unit 3: 卡池状态机与账号元数据扩展**

**Goal:** 为绑卡流程补齐“预占用、失败回写、最近一次绑定信息”等持久化字段。

**Requirements:** R3, R5

**Dependencies:** Unit 1

**Files:**
- Modify: `src/autoteam/card_pool.py`
- Modify: `src/autoteam/accounts.py`
- Modify: `src/autoteam/api.py`
- Modify: `web/src/components/BindCardPool.vue`
- Test: `tests/unit/test_card_pool.py`
- Test: `tests/unit/test_accounts.py`

**Approach:**
- 扩展卡状态枚举：`unused`、`binding`、`used`、`failed`、`expired`。
- 为卡项 `meta` 增加 `last_bind_result`、`last_bind_at`、`last_proxy_label`、`last_account_email`、`bind_attempts`。
- 为账号记录增加 `last_bind_status`、`last_bind_at`、`last_checkout_url`、`last_card_id`、`last_proxy_label`、`last_bind_task_id`。
- 在卡池模块中增加显式辅助函数，避免调用方手写状态转换，例如：
  - 预占卡
  - 成功完成绑定
  - 失败释放或失败固化
- 同步扩展卡池统计与前端状态显示。

**Patterns to follow:**
- `src/autoteam/card_pool.py` 中现有的 `update_item()`
- `src/autoteam/accounts.py` 中现有的 `update_account()`

**Test scenarios:**
- Happy path: 预占一张 `unused` 卡后，状态变为 `binding`，并写入账号/代理元数据。
- Edge case: 已经是 `binding` 或 `used` 的卡再次预占时被拒绝。
- Happy path: 绑定成功后卡状态变为 `used`，`used_by` / `used_at` 被写入。
- Error path: 打开页面失败这类“未提交支付”的错误会把卡从 `binding` 回退到 `unused`。
- Error path: 提交后明确失败时，卡状态变为 `failed` 并保留最近一次失败信息。
- Integration: 账号记录会同步写入最近一次绑卡元数据。

**Verification:**
- 卡池和账号池都能独立反映最近一次绑卡任务的占用与结果。

- [ ] **Unit 4: 绑卡执行器与结果分类**

**Goal:** 新增浏览器执行模块，负责打开 checkout、填卡、人工确认等待、截图和结果分类。

**Requirements:** R4

**Dependencies:** Unit 2, Unit 3

**Files:**
- Create: `src/autoteam/bind_executor.py`
- Modify: `src/autoteam/api.py`
- Test: `tests/unit/test_bind_executor.py`

**Approach:**
- 在 `src/autoteam/bind_executor.py` 中提供单一入口，例如 `run_bind_task(...)`。
- 复用 `ChatGPTTeamAPI` 的浏览器启动与 Cloudflare 等待逻辑，而不是在执行器里重新发明 Playwright 基础设施。
- 执行器最少覆盖这些阶段：
  - `open_checkout`
  - `fill_card`
  - `submit`
  - `post_submit`
- 当 `manual_confirm=true` 时，浏览器保持可见并等待人工在页面内完成确认；执行器只负责轮询结果、超时和最终归类。
- 失败时保存关键截图路径并返回结构化结果：
  - `status`: `success | failed | needs_review`
  - `failure_stage`
  - `message`
  - `proxy_label`
  - `screenshot_paths`

**Execution note:** 先用假页面对象把阶段分类和错误收口测通，再接真实 checkout 页面选择器，避免把选择器调试和状态机调试混在一起。

**Patterns to follow:**
- `src/autoteam/api.py` 中 `POST /api/bind/link` 的页面端 fetch 结果判定
- `src/autoteam/chatgpt_api.py` 中 `_wait_for_cloudflare()`

**Test scenarios:**
- Happy path: 页面可打开、卡信息完整、提交成功时返回 `status=success`。
- Edge case: `manual_confirm=true` 且页面进入待人工确认状态时返回中间可追踪信息，并在最终完成后归类为 `success` 或 `needs_review`。
- Error path: checkout 页面打不开时返回 `failed` 且 `failure_stage=open_checkout`。
- Error path: 卡字段缺失或页面定位失败时返回 `failed` 且 `failure_stage=fill_card`。
- Error path: 提交后页面出现明确拒付/校验失败文案时返回 `failed` 且 `failure_stage=post_submit`。
- Integration: 失败时返回截图路径，便于后续人工核查。

**Verification:**
- 在真实浏览器里，执行器可以稳定完成“打开页面 -> 填卡 -> 等待结果 -> 返回结构化结果”的闭环。

- [ ] **Unit 5: 结果回写与持久化审计**

**Goal:** 把任务结果从“内存态”落到可追溯的持久化记录中，并保证取消/异常也能正确收口。

**Requirements:** R5

**Dependencies:** Unit 3, Unit 4

**Files:**
- Create: `src/autoteam/bind_audit.py`
- Modify: `src/autoteam/api.py`
- Test: `tests/unit/test_bind_audit.py`

**Approach:**
- 参考 `src/autoteam/register_failures.py`，新增绑卡审计存储模块。
- 每个任务结束时至少记录：
  - `task_id`
  - `email`
  - `card_item_id`
  - `checkout_url`
  - `proxy_label`
  - `status`
  - `failure_stage`
  - `message`
  - `started_at`
  - `finished_at`
  - `screenshot_paths`
- 在 `finally` 分支统一收口，确保以下情况都不会遗留脏状态：
  - 任务取消
  - 执行器抛异常
  - 浏览器超时
- 任务结果除了写审计文件，还要同步写回 `_tasks[task_id]["result"]`，保证现有任务页可见。

**Patterns to follow:**
- `src/autoteam/register_failures.py`
- `src/autoteam/api.py` 中现有任务完成后的 `task["result"]` / `task["error"]` 约定

**Test scenarios:**
- Happy path: 成功任务会写入一条完整审计记录。
- Error path: 执行器异常时仍会写审计记录，并释放卡的 `binding` 状态。
- Error path: 取消任务时，`task.status` 变为 `cancelled`，审计结果保留取消原因。
- Integration: `GET /api/tasks/{task_id}` 能看到与审计记录一致的结构化结果。

**Verification:**
- 即使任务历史被内存裁剪，最近一次绑卡结果仍能从持久化审计中追溯。

- [ ] **Unit 6: 前端“开始绑卡”面板与状态展示**

**Goal:** 在现有绑卡页面中把“生成链接”扩展为“生成链接 + 启动绑卡任务 + 查看结果”的操作闭环。

**Requirements:** R6

**Dependencies:** Unit 1, Unit 3, Unit 5

**Files:**
- Modify: `web/src/components/BindCard.vue`
- Modify: `web/src/components/BindCardPool.vue`
- Modify: `web/src/api.js`
- Test: `tests/unit/test_bind_task_api.py`

**Approach:**
- 在 `BindCard.vue` 中新增“开始绑卡”面板，字段至少包括：
  - 账号
  - checkout 链接（默认带入当前生成结果）
  - 卡项
  - 代理标签
  - 代理 URL
  - `manual_confirm`
- 启动任务后，复用现有 `getTask()` 轮询任务状态，不为前端额外发明新协议。
- 在 `BindCardPool.vue` 中补齐 `binding` / `failed` 的筛选、文案和统计展示。
- 当任务完成时，在 `BindCard.vue` 中展示结构化结果摘要，而不是仅显示原始报错字符串。

**Patterns to follow:**
- `web/src/components/BindCard.vue` 中现有的 token 提取与支付链接生成流程
- `web/src/components/TaskPanel.vue` 中现有的任务提交与任务运行态展示方式

**Test scenarios:**
- Happy path: 生成 checkout 链接后可直接发起绑卡任务，请求体包含所选账号、卡、代理和 `manual_confirm`。
- Edge case: 未选择卡或未填写 checkout 链接时，前端阻止提交。
- Edge case: 任务进行中时，重复点击会被禁用。
- Integration: 任务结束后，页面能展示 `success` / `failed` / `needs_review` 的结果摘要。
- Integration: 卡池页面能正确显示 `binding` / `failed` 状态和统计。

**Verification:**
- 用户无需离开现有绑卡页面，就能完成“生成链接 -> 启动任务 -> 查看结果”的操作闭环。

- [ ] **Unit 7: 文档补充与验收清单**

**Goal:** 把新能力的运行方式、限制和人工验收方法固化到文档里。

**Requirements:** R7

**Dependencies:** Unit 2, Unit 6

**Files:**
- Modify: `docs/configuration.md`
- Modify: `docs/api.md`
- Test: `tests/unit/test_bind_task_api.py`

**Approach:**
- 在 `docs/configuration.md` 说明“全局代理”与“任务级代理”的关系和优先级。
- 在 `docs/api.md` 补充 `POST /api/tasks/bind-card` 请求体和结果结构。
- 增加一份人工验收清单，覆盖：
  - 有代理 / 无代理
  - `custom` / `hosted`
  - 手工确认完成
  - 明确失败回写

**Patterns to follow:**
- `docs/configuration.md` 中现有 Playwright 代理说明
- `docs/api.md` 中现有 API 文档风格

**Test scenarios:**
- Integration: API 文档里的请求体与真实接口字段保持一致。
- Integration: 配置文档明确说明任务级代理不会改写全局 `.env`。

**Verification:**
- 新能力上线后，维护者只靠仓库文档即可完成基础配置与人工验收。

## System-Wide Impact

- **Interaction graph:** `BindCard.vue` -> `POST /api/tasks/bind-card` -> `_start_task()` -> `bind_executor.py` -> `ChatGPTTeamAPI` -> `card_pool.py` / `accounts.py` / `bind_audit.py`
- **Error propagation:** 执行器内部异常需要被转换成结构化结果，不能只在任务历史里留下裸字符串异常。
- **State lifecycle risks:** 最大风险是卡项停留在 `binding`；所有收口路径都必须在 `finally` 中做状态释放或固化。
- **API surface parity:** 任务状态查询继续复用 `/api/tasks/{task_id}`，避免产生两套任务查询协议。
- **Integration coverage:** 至少验证一次真实浏览器下的 `manual_confirm=true` 闭环，因为这条路径跨越了前端、任务层、Playwright 和持久化层。
- **Unchanged invariants:** 现有 `POST /api/bind/link`、卡池导入/兑换、全局 Playwright 代理配置仍保持向后兼容。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| checkout 页面 DOM 结构易变 | 把页面选择器集中在 `bind_executor.py`，并保留 `manual_confirm` 兜底 |
| 任务取消或异常导致卡长期停留 `binding` | 所有退出路径统一进入状态收口逻辑，并为此补单测 |
| 任务级代理改动影响其他浏览器流程 | 代理参数只做可选 override，不改现有调用点默认行为 |
| 前端缺少现成 Vue 测试基建 | 先用 API/状态流单测兜底，前端以人工闭环验收补充 |
| 审计只存在内存任务历史中会丢失 | 单独增加 `bind_audit.py` 持久化审计文件 |

## Documentation / Operational Notes

- 绑卡截图建议统一落到 `data/` 下独立目录，便于人工复查和定期清理。
- `manual_confirm=true` 需要明确超时策略，否则后台任务会长时间占用唯一的 Playwright 执行通道。
- 如果后续接入短信自动回填，优先抽取可复用的短信拉取 helper，而不是从前端 API 逻辑反向复制一份。

## Sources & References

- **Origin document:** `docs/auto_bind_plan.md`
- Related code: `src/autoteam/api.py`
- Related code: `src/autoteam/config.py`
- Related code: `src/autoteam/chatgpt_api.py`
- Related code: `src/autoteam/card_pool.py`
- Related code: `src/autoteam/accounts.py`
- Related code: `web/src/components/BindCard.vue`
- Related code: `web/src/components/BindCardPool.vue`
