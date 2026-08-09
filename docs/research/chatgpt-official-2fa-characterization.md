# ChatGPT 官方 TOTP 2FA 流程刻画

日期：2026-08-09

## 结论

当前 ChatGPT Web 可以通过官方 UI 完成 Authenticator App / TOTP MFA 设置，不需要调用第三方 `Nerver` 类接口，也不需要识别二维码图片。

可执行路径：

1. 登录 `https://chatgpt.com/auth/login`。
2. 打开 `https://chatgpt.com/#settings/Security`。
3. 在安全设置中点击 `Authenticator app` 开关。
4. 如果跳转到 `https://auth.openai.com/email-verification`，先完成 recent-auth 邮箱验证码。
5. 回到 Security 设置后，等待 `关联身份验证器应用` / `Authenticator app` 对话框。
6. 从 DOM 中读取 `a[href^="otpauth://totp/"]`，其 `href` 形如：
   `otpauth://totp/OpenAI:<email>?secret=<BASE32_SECRET>&issuer=OpenAI`
7. 本地按 RFC 6238 / SHA1 / 30 秒步长 / 6 位生成 TOTP。
8. 将验证码填入 `输入 6 位验证码` / equivalent textbox，点击 `验证` / `Verify`。
9. 成功后 `Authenticator app` 开关为 checked，并显示添加备用方法的提示。

## 已观察到的 UI 状态

### 正常登录 / 注册

- 使用 `@openaibus.com` 测试邮箱注册时，OpenAI 发送邮箱一次性验证码。
- 新账号可能走 passwordless/email-code 注册流程，不要求设置密码。
- 首次进入 ChatGPT 前可能要求填写 full name 和 age。

### Recent auth

启用 Authenticator App 时，OpenAI 可能要求 recent-auth：

- URL：`https://auth.openai.com/email-verification`
- 邮件主题类似：`你的临时 ChatGPT 登录代码`
- 验证通过后返回：`https://chatgpt.com/#settings/Security`

### TOTP secret 暴露方式

设置弹窗中的二维码区域同时包含一个 `otpauth://totp/` 链接，所以自动化应优先读取 DOM 链接，不做 OCR、不解码图片。

链接参数中包含：

- label：通常是 `OpenAI:<email>`
- `secret`：Base32 TOTP secret
- `issuer`：`OpenAI`

## 协议观察

点击 Authenticator App 后曾观察到 same-origin / first-party NextAuth reauth 请求：

```text
POST https://chatgpt.com/api/auth/signin/openai?connection=password&login_hint=<email>&reauth=password&max_age=0&...
```

`callbackUrl` 包含：

```text
https://chatgpt.com/?action=enable&factor=totp#settings/Security
```

目前实现策略仍以 UI 自动化为主。只有在后续完整刻画请求、响应、CSRF 和错误状态后，才考虑协议化调用。

## 推荐选择器策略

优先顺序：

1. DOM：`a[href^="otpauth://totp/"]`
2. 语义文本：`Authenticator app` / `身份验证器应用`
3. 弹窗标题：`关联身份验证器应用` / `Authenticator app`
4. 输入框：`输入 6 位验证码` / `6-digit code` / `verification code`
5. 验证按钮：`验证` / `Verify`

## 已知阻塞与恢复

- **MFA option 不可见**：记录 unsupported state，不继续猜测接口。
- **recent-auth 验证失败**：保留 browser/session 状态，返回可恢复错误。
- **无法读取 otpauth 链接**：不要从日志输出二维码或 secret；返回 `secret_unavailable` 类错误。
- **已启用但本地无 secret**：标记为 manual recovery，不能伪造 secret。
- **TOTP 验证失败**：可以尝试 previous/current/next 时间窗口候选，但不要记录验证码。

## 敏感信息处理

以下内容视为凭据，不写入普通日志、任务进度、默认导出或错误消息：

- TOTP raw secret
- 生成的 6 位 TOTP code
- 邮箱验证码
- 完整 `otpauth://` URI

默认只展示 masked secret，例如 `ABCD…WXYZ`。
