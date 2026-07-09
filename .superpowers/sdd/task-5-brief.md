### Task 5: End-to-end verification and service restart

**Files:**
- No new code expected.
- Verify: backend tests, frontend build, app behavior.

**Interfaces:**
- Consumes all previous tasks.
- Produces a restarted local service with updated code.

- [ ] **Step 1: Run full targeted backend test suite**

Run:

```powershell
pytest tests/unit/test_mail_accounts.py tests/unit/test_mail_accounts_routes.py tests/unit/test_mailcom_mail.py tests/unit/test_account_register_task_routes.py tests/unit/test_manager_mailcom_sync.py tests/unit/test_mailcom_webmail_service.py tests/unit/test_mailcom_password_service.py tests/unit/test_outlook_mail.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 3: Restart the service**

Use the project’s existing service start command discovered from current process or project scripts. If the previous service is still running, stop only that project process, then start the same command again.

Concrete PowerShell pattern:

```powershell
Get-Process -Name python,node -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*AutoTeam-F*' } | Select-Object Id,ProcessName,Path
```

Then use the exact existing run command from the project script or previous terminal output. Do not kill unrelated Python or Node processes.

- [ ] **Step 4: Manual smoke test in UI**

1. Open 注册账户 page.
2. Select `mail.com` as 邮件供应商.
3. Confirm the `mail.com 邮箱池` card appears.
4. Import one test line:

```text
test@mail.com----gpt-password----mail-password----rt-token
```

5. Confirm import response shows synced account pool and login-batch task starts.
6. Confirm account appears in the 账号池 page.
7. Confirm mail.com 邮箱池 status changes after the login task completes.

- [ ] **Step 5: Final status**

Run:

```powershell
git status --short
```

Expected: clean working tree after commits, or only intentional uncommitted runtime files ignored by git.


