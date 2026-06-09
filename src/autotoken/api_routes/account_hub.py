"""Account Hub HTTP routes."""

import time
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import AliasChoices, BaseModel, Field

from autotoken.api_routes.input_limits import validate_list_payload_limit

ACCOUNT_HUB_SYNC_MAX_EMAILS = 1_000
ACCOUNT_HUB_INGEST_MAX_ITEMS = 1_000


class AccountHubConfigParams(BaseModel):
    url: str = ""
    token: str = ""
    name: str = ""
    auto_upload: bool = Field(False, validation_alias=AliasChoices("auto_upload", "autoUpload"))


class AccountHubIngestPayload(BaseModel):
    source: dict = Field(default_factory=dict)
    accounts: list[dict] = Field(default_factory=list)
    auths: list[dict] = Field(default_factory=list)
    auth_sessions: list[dict] = Field(default_factory=list)


class AccountHubSyncParams(BaseModel):
    emails: list[str] = Field(default_factory=list)


def create_account_hub_router(*, normalize_email: Callable[[str | None], str]) -> APIRouter:
    router = APIRouter()

    def require_account_hub_token(request: Request) -> None:
        from autotoken.integrations.account_hub import expected_inbound_token

        expected = expected_inbound_token()
        if not expected:
            raise HTTPException(status_code=403, detail="账号 Hub Token 未配置")
        token = request.headers.get("x-account-hub-token", "")
        if token != expected:
            raise HTTPException(status_code=401, detail="账号 Hub Token 无效")

    @router.get("/api/account-hub/config")
    def get_account_hub_config():
        from autotoken.integrations.account_hub import get_config

        return get_config()

    @router.put("/api/account-hub/config")
    def put_account_hub_config(params: AccountHubConfigParams):
        from autotoken.integrations.account_hub import set_config

        saved = set_config(params.model_dump())
        return {"message": "远程账号 Hub 配置已保存", "config": saved}

    @router.post("/api/account-hub/test")
    def post_account_hub_test(params: AccountHubConfigParams):
        from autotoken.integrations.account_hub import test_connection

        try:
            return test_connection(params.model_dump())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/account-hub/sync")
    def post_account_hub_sync(params: AccountHubSyncParams):
        from autotoken.integrations.account_hub import upload_to_hub

        validate_list_payload_limit(params.emails, max_items=ACCOUNT_HUB_SYNC_MAX_EMAILS, label="账号 Hub 同步")
        emails = [normalize_email(email) for email in (params.emails or []) if normalize_email(email)]
        if not emails:
            raise HTTPException(status_code=400, detail="请选择要同步到账号 Hub 的账号")
        try:
            return upload_to_hub(selected_emails=emails)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/account-hub/ping")
    def post_account_hub_ping(request: Request):
        require_account_hub_token(request)
        return {"ok": True, "message": "账号 Hub 连接成功", "time": time.time()}

    @router.post("/api/account-hub/ingest")
    def post_account_hub_ingest(request: Request, payload: AccountHubIngestPayload):
        require_account_hub_token(request)
        from autotoken.integrations.account_hub import receive_payload

        validate_list_payload_limit(payload.accounts, max_items=ACCOUNT_HUB_INGEST_MAX_ITEMS, label="账号 Hub 入站账号")
        validate_list_payload_limit(payload.auths, max_items=ACCOUNT_HUB_INGEST_MAX_ITEMS, label="账号 Hub 入站 auth")
        validate_list_payload_limit(
            payload.auth_sessions,
            max_items=ACCOUNT_HUB_INGEST_MAX_ITEMS,
            label="账号 Hub 入站 auth session",
        )
        try:
            return receive_payload(payload.model_dump())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
