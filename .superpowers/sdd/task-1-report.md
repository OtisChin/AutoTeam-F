status: DONE_WITH_CONCERNS

## 修改文件列表
- src/autotoken/integrations/go_protocol_register_client.py
- tests/unit/test_go_protocol_register_client.py
- tests/fixtures/go_protocol_register/register_request_generic_api.json
- tests/fixtures/go_protocol_register/register_success_response.json
- tests/fixtures/go_protocol_register/email_code_timeout_response.json
- tests/fixtures/go_protocol_register/phone_required_response.json

## 测试命令和输出摘要
- $env:PYTHONIOENCODING='utf-8'; uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py -q（TDD RED：导入失败，ModuleNotFoundError，符合实现缺失预期）
- $env:PYTHONIOENCODING='utf-8'; uv run --no-sync pytest tests/unit/test_go_protocol_register_client.py -q（GREEN：4 passed in 0.15s）
- 提交后复跑同一命令：4 passed。
- git diff --check：通过。

## commit hash
4d2929dd63f5601c1aa3e3f9ab2f88ffffb05d94

## self-review
- 已按 email-first contract 创建四个 JSON fixtures。
- wrapper 默认地址为 http://127.0.0.1:18787，支持 GO_PROTOCOL_REGISTER_URL，并提供 /healthz 与 /v1/register 调用。
- 成功、邮箱验证码超时、手机号要求响应均映射到 protocol result；连接、超时、无效 JSON 转换为 GoProtocolRegisterUnavailable。
- 仅提交 Task 1 brief 列出的六个实现/测试/fixture 文件；未触碰工作区中其他既有 dirty changes。
- 未运行全量测试，因此全量回归状态未确认。

## concerns
- 工作区存在其他用户/历史 dirty changes，未纳入本次提交。
- 本任务仅验证目标单测，未运行完整测试套件。
