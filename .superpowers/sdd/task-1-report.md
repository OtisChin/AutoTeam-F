STATUS: DONE

变更文件:
- D:/code/OpenSource/AutoTeam-F/src/autotoken/storage/mail_accounts.py
- D:/code/OpenSource/AutoTeam-F/src/autotoken/mail/mailcom.py
- D:/code/OpenSource/AutoTeam-F/src/autotoken/mail/__init__.py
- D:/code/OpenSource/AutoTeam-F/src/autotoken/settings/setup_wizard.py
- D:/code/OpenSource/AutoTeam-F/tests/unit/test_mail_accounts.py
- D:/code/OpenSource/AutoTeam-F/tests/unit/test_mailcom_mail.py

提交 hash:
- b57c7d6

运行的测试命令和结果:
- .\\.venv\\Scripts\\python.exe -m pytest tests/unit/test_mail_accounts.py -q
  - 第一次（RED）: 4 failed, 5 passed；失败原因符合预期：mailcom_pool_status / sync_mail_accounts_to_account_pool / list_available_registration_accounts / mark_mailcom_registered 缺失
  - 第二次（GREEN）: 9 passed
- .\\.venv\\Scripts\\python.exe -m pytest tests/unit/test_mailcom_mail.py -q
  - 第一次（RED）: collection error；失败原因符合预期：autotoken.mail.mailcom 不存在
- .\\.venv\\Scripts\\python.exe -m pytest tests/unit/test_mailcom_mail.py tests/unit/test_mail_provider_config_routes.py -q
  - GREEN: 7 passed

自审结论:
- 已按 TDD 先补失败测试，再实现最小代码通过。
- 仅改动 brief 指定的 Task 1 代码/测试文件；未触碰用户明确禁止的无关文件。
- provider 工厂与 setup wizard 已接入 mail.com，storage helper 与 mail.com provider 行为均由单测覆盖。

任何顾虑:
- 无。
