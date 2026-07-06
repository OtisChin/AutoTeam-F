状态: DONE_WITH_CONCERNS

变更文件:
- D:\code\OpenSource\AutoTeam-F\web\src\api.js
- D:\code\OpenSource\AutoTeam-F\web\src\components\RegisterAccountPage.vue

提交 hash:
- 442a410

运行的构建命令和结果:
- 命令: npm --prefix web run build
- 结果: 成功（exit code 0）
- 摘要: vite build 通过；产物生成到 src/autotoken/web/dist；仍有 1 条 chunk size warning（index-CAEOpnV3.js 约 820.70 kB）

自审结论:
- 已为 mail.com 注册供应商补齐邮箱池 API 调用与页面 UI。
- 导入后的自动登录、管理弹窗里的“登录并入池/重试”均调用 login-batch，并固定传入：mail_provider='mail.com'、protocol_only=true、bind_email=false。
- 未添加会触发浏览器/Playwright 登录的 mail.com 按钮或参数。
- 任务完成后会在 provider 切换、页面挂载、任务结束时刷新 mail.com 邮箱池状态。
- 提交时仅暂存并提交 brief 允许的两个代码文件，未碰用户列出的无关文件。

顾虑:
- brief 限制只改两个实现文件，未新增前端自动化测试；本次验证仅覆盖构建成功。
- 构建存在既有 chunk size warning，但不影响本次 build 成功。
## 2026-07-06 Task 4 follow-up fix (Important)
- 修复 `web/src/components/RegisterAccountPage.vue` 中 `registerProviderUsesPool` 回归：恢复 LuckMail、Outlook、mail.com 三者都走邮箱池逻辑。
- 恢复 `registerProviderPoolMessage` 的 LuckMail/Outlook 原有说明；保留 mail.com 的邮箱池说明。
- 保持 `registerProviderUsesDomains` 依赖池逻辑，确保 LuckMail 不再显示或提交通用注册域名。
- 未改动 mail.com 登录并入池调用参数；仍固定传 `mail_provider: 'mail.com'`、`protocol_only: true`、`bind_email: false`，未添加浏览器/Playwright 参数。
- 未修改 `web/src/api.js` 的 ideal API minor 相关内容。

### 验证
- 命令：`npm --prefix web run build`
- 结果：成功（exit code 0）
- 摘要：Vite build 通过，产物输出到 `src/autotoken/web/dist/`；仍有既有 chunk size warning（`assets/index-CTrcR7hK.js` 约 820.89 kB）。
## 2026-07-06 Task 4 second follow-up fix (Important)
- 在 `web/src/components/RegisterAccountPage.vue` 的 `importMailComAccounts()` 增加前端预校验：逐行解析首字段邮箱，发现非 `@mail.com` 行时在调用 `api.importMailAccounts()` 前直接拒绝并提示行号/邮箱预览。
- 将 `mailComPoolItems` 改为仅保留 `@mail.com` 记录，避免管理弹窗展示、选择或操作非 mail.com 数据；相关选择与登录候选邮箱也统一使用规范化后的 `mail.com` 邮箱值。
- 为导入后自动登录入池补上兜底：当 `result.synced_account_pool?.emails` 为空时，额外调用 `api.syncMailAccountsToAccountPool()`，并优先传入导入内容中解析出的 `@mail.com` 邮箱列表；仅在 sync 返回邮箱后再调用 `loginAccountsBatch()`。
- `loginAccountsBatch()` 调用保持固定参数：`mail_provider: 'mail.com'`、`protocol_only: true`、`bind_email: false`；未增加浏览器/Playwright 参数。
- 未改动 `web/src/api.js` 的 ideal API minor 相关内容。

### 验证
- 命令：`npm --prefix web run build`
- 结果：成功（exit code 0）
- 摘要：Vite build 通过，产物输出到 `src/autotoken/web/dist/`；仍有既有 chunk size warning（`assets/index-DNiM5DUU.js` 约 821.98 kB）。
