Status: DONE

Changed Files:
- D:/code/OpenSource/AutoTeam-F/src/autotoken/interfaces/manager.py
- D:/code/OpenSource/AutoTeam-F/tests/unit/test_manager_mailcom_sync.py

Commit:
- 3209fff200fe9b2b1f8d060fbd8e1e94bc4e8ec5

Test Commands and Results:
- `pytest tests/unit/test_manager_mailcom_sync.py -q` -> failed to launch because `pytest` was not on PATH in this shell.
- `.venv\\Scripts\\python.exe -m pytest tests/unit/test_manager_mailcom_sync.py -q` -> RED, 2 failed as expected (`_sync_provider_registered_email` missing).
- `.venv\\Scripts\\python.exe -m pytest tests/unit/test_manager_mailcom_sync.py tests/unit/test_manager_mail_timeout.py tests/unit/test_account_register_task_routes.py -q` -> GREEN, 13 passed.

Self Review:
- Added a provider-agnostic registration sync helper in manager while preserving Outlook compatibility via the existing wrapper.
- Hooked mail.com sync into the two Task 3-required success paths: registration success and auth_session save.
- Added focused unit coverage for both mail.com and Outlook behavior.
- Kept changes limited to the Task 3 code/test files plus this report file; did not touch the unrelated modified/untracked workspace files listed by the user.

Concerns:
- None blocking. `refresh_token` support exists in the new helper signature, but Task 3's specified call sites only provided `password`/`source`, so no additional refresh-token propagation was added beyond the brief.

## 2026-07-06 Task 3 follow-up fix

- 修复 `_save_codex_oauth_bundle_for_account()` 中遗留的 `_mark_outlook_email_registered(...)` 调用，改为 `_sync_provider_registered_email(...)`，并传递 `mail_provider`、`password`、`refresh_token`、`source`。
- 修复 `email_already_in_use` 分支的遗留 Outlook 专用 wrapper 调用，改为通用 `_sync_provider_registered_email(...)`，并传递 `password`、`source`。
- 补充轻量测试，覆盖：
  - `_save_codex_oauth_bundle_for_account()` 不再经过旧 wrapper；
  - duplicate email 分支不再经过旧 wrapper，而是命中新通用 helper。

测试命令：
- `.venv\\Scripts\\python.exe -m pytest tests/unit/test_manager_mailcom_sync.py tests/unit/test_manager_mail_timeout.py tests/unit/test_account_register_task_routes.py -q`

测试结果：
- `15 passed in 0.48s`
