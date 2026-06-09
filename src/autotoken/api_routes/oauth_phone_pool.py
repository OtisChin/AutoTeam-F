"""OAuth phone pool HTTP routes."""

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

from autotoken.api_routes.input_limits import validate_list_payload_limit, validate_text_payload_limits

OAUTH_PHONE_POOL_IMPORT_MAX_BYTES = 2 * 1024 * 1024
OAUTH_PHONE_POOL_IMPORT_MAX_LINES = 10_000
OAUTH_PHONE_POOL_DELETE_MAX_IDS = 1_000


class OAuthPhonePoolImportParams(BaseModel):
    text: str


class OAuthPhonePoolUpsertParams(BaseModel):
    id: str = ""
    phone_number: str = Field("", validation_alias=AliasChoices("phone_number", "phoneNumber"))
    sms_url: str = Field("", validation_alias=AliasChoices("sms_url", "smsUrl"))
    status: str = "available"
    bound_count: int = Field(0, validation_alias=AliasChoices("bound_count", "boundCount"))
    bound_emails: list[str] = Field(default_factory=list, validation_alias=AliasChoices("bound_emails", "boundEmails"))
    invalid_reason: str = Field("", validation_alias=AliasChoices("invalid_reason", "invalidReason"))
    cooldown_until: float | None = Field(None, validation_alias=AliasChoices("cooldown_until", "cooldownUntil"))
    note: str = ""


class OAuthPhonePoolDeleteParams(BaseModel):
    ids: list[str]


def _phone_pool_response(items: list[dict]) -> dict:
    return {
        "items": items,
        "total": len(items),
        "available_count": sum(1 for item in items if item.get("status") == "available"),
        "full_count": sum(1 for item in items if item.get("status") == "full"),
        "invalid_count": sum(1 for item in items if item.get("status") == "invalid"),
        "cooldown_count": sum(1 for item in items if item.get("status") == "cooldown"),
        "disabled_count": sum(1 for item in items if item.get("status") == "disabled"),
    }


def _phone_records_response(items: list[dict]) -> dict:
    return {
        "items": items,
        "total": len(items),
        "success_count": sum(1 for item in items if str(item.get("status") or "").startswith("success")),
        "active_count": sum(1 for item in items if item.get("status") == "acquired"),
        "cancelled_count": sum(1 for item in items if item.get("status") == "cancelled"),
        "failed_count": sum(1 for item in items if item.get("status") in {"failed", "invalid", "cooldown"}),
    }


def create_oauth_phone_pool_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/oauth-phone-pool")
    def get_oauth_phone_pool():
        from autotoken.auth.oauth_phone_pool import list_phones

        return _phone_pool_response(list_phones())

    @router.get("/api/oauth-phone-records")
    def get_oauth_phone_records(limit: int = 300):
        from autotoken.auth.oauth_phone_records import list_records

        return _phone_records_response(list_records(limit=limit))

    @router.post("/api/oauth-phone-pool/import")
    def post_oauth_phone_pool_import(params: OAuthPhonePoolImportParams):
        from autotoken.auth.oauth_phone_pool import import_phones

        try:
            validate_text_payload_limits(
                params.text,
                max_bytes=OAUTH_PHONE_POOL_IMPORT_MAX_BYTES,
                max_lines=OAUTH_PHONE_POOL_IMPORT_MAX_LINES,
                label="OAuth 手机池导入",
            )
            return import_phones(params.text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/oauth-phone-pool")
    def post_oauth_phone_pool_item(params: OAuthPhonePoolUpsertParams):
        from autotoken.auth.oauth_phone_pool import upsert_phone

        try:
            return upsert_phone(params.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/api/oauth-phone-pool/{item_id}")
    def put_oauth_phone_pool_item(item_id: str, params: OAuthPhonePoolUpsertParams):
        from autotoken.auth.oauth_phone_pool import update_phone

        try:
            return update_phone(item_id, params.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/oauth-phone-pool/delete")
    def post_oauth_phone_pool_delete(params: OAuthPhonePoolDeleteParams):
        from autotoken.auth.oauth_phone_pool import delete_phones, list_phones

        validate_list_payload_limit(params.ids, max_items=OAUTH_PHONE_POOL_DELETE_MAX_IDS, label="OAuth 手机池删除")
        deleted = delete_phones(params.ids)
        items = list_phones()
        return {"deleted": deleted, "items": items, "total": len(items)}

    return router
