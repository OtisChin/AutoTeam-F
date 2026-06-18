"""PayPal ICE phone pool HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

PAYPAL_ICE_PHONE_POOL_DELETE_MAX_IDS = 1_000


class PayPalIcePhonePoolAddParams(BaseModel):
    phone_number: str = Field("", validation_alias="phoneNumber")
    sms_api: str = Field("", validation_alias="smsApi")
    note: str = ""


class PayPalIcePhonePoolUpdateParams(BaseModel):
    phone_number: str = Field("", validation_alias="phoneNumber")
    sms_api: str = Field("", validation_alias="smsApi")
    status: str = ""
    note: str = ""
    error_message: str = Field("", validation_alias="errorMessage")


class PayPalIcePhonePoolDeleteParams(BaseModel):
    ids: list[str]


class PayPalIcePhonePoolImportParams(BaseModel):
    text: str


class PayPalIcePhonePoolReleaseParams(BaseModel):
    phone_ids: list[str] = Field(default_factory=list, validation_alias="phoneIds")
    job_ids: list[str] = Field(default_factory=list, validation_alias="jobIds")


def create_paypal_ice_phone_pool_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/paypal-ice/phone-pool")
    def get_phone_pool():
        from autotoken.services.paypal_ice_phone_pool import list_phones, pool_stats

        return {
            "items": list_phones(),
            "stats": pool_stats(),
        }

    @router.post("/api/paypal-ice/phone-pool")
    def add_phone(params: PayPalIcePhonePoolAddParams):
        from autotoken.services.paypal_ice_phone_pool import add_phone, list_phones, pool_stats

        try:
            item = add_phone({"phone_number": params.phone_number, "sms_api": params.sms_api, "note": params.note})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "message": f"已添加手机号 {item['phone_number']}",
            "item": item,
            "items": list_phones(),
            "stats": pool_stats(),
        }

    @router.get("/api/paypal-ice/phone-pool/stats")
    def get_phone_pool_stats():
        from autotoken.services.paypal_ice_phone_pool import pool_stats

        return pool_stats()

    @router.put("/api/paypal-ice/phone-pool/{item_id}")
    def update_phone(item_id: str, params: PayPalIcePhonePoolUpdateParams):
        from autotoken.services.paypal_ice_phone_pool import update_phone

        payload = {}
        for field in ("phone_number", "sms_api", "status", "note", "error_message"):
            if field in params.model_fields_set:
                payload[field] = getattr(params, field)
        try:
            return update_phone(item_id, payload)
        except KeyError:
            raise HTTPException(status_code=404, detail="手机号不存在")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/paypal-ice/phone-pool/delete")
    def delete_phones(params: PayPalIcePhonePoolDeleteParams):
        from autotoken.services.paypal_ice_phone_pool import delete_phones, list_phones, pool_stats

        if len(params.ids or []) > PAYPAL_ICE_PHONE_POOL_DELETE_MAX_IDS:
            raise HTTPException(status_code=400, detail=f"最多支持删除 {PAYPAL_ICE_PHONE_POOL_DELETE_MAX_IDS} 条")
        deleted = delete_phones(params.ids)
        return {
            "deleted": deleted,
            "items": list_phones(),
            "stats": pool_stats(),
        }

    @router.post("/api/paypal-ice/phone-pool/import")
    def import_phones(params: PayPalIcePhonePoolImportParams):
        from autotoken.services.paypal_ice_phone_pool import import_phones

        try:
            result = import_phones(params.text)
            return {
                "message": f"导入成功 {result['added']} 条，跳过 {result['skipped']} 条",
                "result": result,
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get(
        "/api/paypal-ice/phone-pool/export",
        response_class=PlainTextResponse,
    )
    def export_phones():
        from autotoken.services.paypal_ice_phone_pool import list_phones

        items = list_phones()
        lines: list[str] = []
        for item in items:
            phone = item.get("phone_number", "")
            api_url = item.get("sms_api", "")
            if phone and api_url:
                lines.append(f"{phone}----{api_url}")
        return PlainTextResponse(
            "\n".join(lines), media_type="text/plain; charset=utf-8"
        )

    @router.post("/api/paypal-ice/phone-pool/release")
    def release_phones(params: PayPalIcePhonePoolReleaseParams):
        from autotoken.services.paypal_ice_phone_pool import list_phones, pool_stats, release_phone

        released_ids = list(params.phone_ids or [])
        for jid in (params.job_ids or []):
            pid = _phone_for_job(jid)
            if pid:
                released_ids.append(pid)
        released = 0
        for pid in released_ids:
            if release_phone(pid):
                released += 1
        return {
            "released": released,
            "items": list_phones(),
            "stats": pool_stats(),
        }

    return router


def _phone_for_job(job_id: str) -> str | None:
    try:
        from autotoken.services.paypal_ice_phone_pool import phone_for_job

        return phone_for_job(job_id)
    except Exception:
        return None
