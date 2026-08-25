status: DONE_WITH_CONCERNS

修改文件列表:
- go/protocol-register/go.mod
- go/protocol-register/cmd/protocol-registerd/main.go
- go/protocol-register/internal/model/request.go
- go/protocol-register/internal/model/response.go
- go/protocol-register/internal/server/server.go
- go/protocol-register/internal/server/routes.go
- go/protocol-register/internal/register/engine.go
- go/protocol-register/internal/register/errors.go
- go/protocol-register/internal/server/routes_test.go

测试命令和输出摘要:
- RED: cd go/protocol-register; go test ./... -> FAIL（模块不存在，"does not contain main module"）。
- GREEN: cd go/protocol-register; go test -v ./... -> PASS；server tests 2/2 通过，其他 Go packages 编译通过。
- 额外: git diff --check -> 通过。
- 尝试 go test -race ./... 未能执行：环境要求 cgo；设置 CGO_ENABLED=1 后因缺少 gcc 编译器失败。

commit hash: 2dafd76cfbc438f27d0e9acdcd00675dd164bc77

self-review:
- 已实现 loopback 默认地址 127.0.0.1:18787、并发上限默认 50、/healthz、/v1/register、请求体 1 MiB 限制、busy admission 响应和 not-found 响应。
- 未修改 brief 之外的 Go 文件；Go 服务不执行账号持久化或 data/auth_session 写入。
- 测试覆盖健康检查与达到并发上限时返回 429；未能完成 race 检测是环境限制。

## Task 2 reviewer fixes

修复内容:
- 将 Go service 的 `not_implemented`、`busy` top-level status 分别改为 `register_failed`，并保留原 `error.code`。
- 将 malformed request 的 top-level status 从 `bad_request` 改为 `exception`，并保留 `error.code: bad_request`。
- 将并发测试改为通过 `entered` channel 确认第一个请求已进入 engine 后再发起第二个请求，移除固定 sleep；同时断言兼容 status 与细分 error code。

测试命令与输出摘要:
- `cd go/protocol-register; go test ./...`
- 输出：`ok autoteam-f/protocol-register/cmd/protocol-registerd`、`ok autoteam-f/protocol-register/internal/server`；`internal/model` 与 `internal/register` 编译通过且无测试；命令退出码 0。

commit:
- 提交：`fix(protocol): align Go service error statuses`

concerns:
- 未运行 `go test -race ./...`；此前环境缺少 gcc/cgo，覆盖测试按要求已完成。
