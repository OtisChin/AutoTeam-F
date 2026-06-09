"""Card pool HTTP routes."""

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from autotoken.api_routes.input_limits import validate_list_payload_limit, validate_text_payload_limits

CARD_POOL_IMPORT_MAX_BYTES = 2 * 1024 * 1024
CARD_POOL_IMPORT_MAX_LINES = 10_000
CARD_POOL_DELETE_MAX_IDS = 1_000
CARD_POOL_REDEEM_BATCH_MAX_IDS = 1_000


class CardPoolImportParams(BaseModel):
    pool_type: str
    text: str
    provider: str = ""


class CardPoolDeleteParams(BaseModel):
    pool_type: str
    ids: list[str]


class CardPoolUpdateParams(BaseModel):
    pool_type: str
    item_id: str
    status: str | None = None
    provider: str | None = None
    used_by: str | None = None
    expires_at: str | None = None


class CardPoolRedeemParams(BaseModel):
    item_id: str


class CardPoolRedeemBatchParams(BaseModel):
    item_ids: list[str]


class CardPoolFetchSmsParams(BaseModel):
    url: str


def create_card_pool_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/card-pool/{pool_type}")
    def get_card_pool(pool_type: str):
        from autotoken.payments.card_pool import list_items, stats_for

        try:
            return {
                "pool_type": pool_type,
                "stats": stats_for(pool_type),
                "items": list_items(pool_type),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/card-pool/import")
    def post_card_pool_import(params: CardPoolImportParams):
        from autotoken.payments.card_pool import import_text_lines, stats_for

        try:
            validate_text_payload_limits(
                params.text,
                max_bytes=CARD_POOL_IMPORT_MAX_BYTES,
                max_lines=CARD_POOL_IMPORT_MAX_LINES,
                label="卡池导入",
            )
            items = import_text_lines(params.pool_type, params.text, provider=params.provider)
            return {
                "message": f"导入成功，新增 {len(items)} 条",
                "imported": items,
                "stats": stats_for(params.pool_type),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/card-pool/delete")
    def post_card_pool_delete(params: CardPoolDeleteParams):
        from autotoken.payments.card_pool import delete_items, stats_for

        try:
            validate_list_payload_limit(params.ids, max_items=CARD_POOL_DELETE_MAX_IDS, label="卡池删除")
            deleted = delete_items(params.pool_type, params.ids)
            return {
                "message": f"已删除 {deleted} 条记录",
                "deleted": deleted,
                "stats": stats_for(params.pool_type),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/card-pool/update")
    def post_card_pool_update(params: CardPoolUpdateParams):
        from autotoken.payments.card_pool import stats_for, update_item

        try:
            item = update_item(
                params.pool_type,
                params.item_id,
                status=params.status,
                provider=params.provider,
                used_by=params.used_by,
                expires_at=params.expires_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not item:
            raise HTTPException(status_code=404, detail="记录不存在")

        return {
            "message": "更新成功",
            "item": item,
            "stats": stats_for(params.pool_type),
        }

    @router.post("/api/card-pool/redeem")
    def post_card_pool_redeem(params: CardPoolRedeemParams):
        from autotoken.payments.card_pool import add_card_item, find_item, stats_for, update_item

        redeem_item = find_item("redeem", params.item_id)
        if not redeem_item:
            raise HTTPException(status_code=404, detail="兑换码不存在")

        code = str(redeem_item.get("value") or "").strip()
        provider = str(redeem_item.get("provider") or "").strip().upper()
        if not code:
            raise HTTPException(status_code=400, detail="兑换码为空")
        if redeem_item.get("status") == "used":
            raise HTTPException(status_code=400, detail="该兑换码已使用")

        if provider not in {"988", "EFUN"}:
            raise HTTPException(status_code=400, detail="暂不支持该供应商兑换")

        if provider == "EFUN":
            url = "https://card.efuncard.com/api/external/redeem"
            headers = {
                "Authorization": "Bearer b352d13f20462ed46cff0aa417065496bd811eb8396b2e2fee11aeacb796fc00",
                "Content-Type": "application/json",
            }
            resp = requests.post(url, json={"code": code}, headers=headers, timeout=30, verify=False)
            try:
                data = resp.json()
            except ValueError as exc:
                raise HTTPException(
                    status_code=502, detail=f"EFUN 返回了非 JSON 响应: {(resp.text or '')[:200]}"
                ) from exc
            if not resp.ok or not data.get("success"):
                raise HTTPException(
                    status_code=resp.status_code or 502,
                    detail=data.get("message") or f"EFUN 兑换失败({resp.status_code})",
                )
            card = data.get("data") or {}
            card_number = str(card.get("cardNumber") or "").strip()
            if not card_number:
                raise HTTPException(status_code=502, detail="EFUN 返回缺少卡券信息")
            card_item = add_card_item(
                value=card_number,
                provider=provider,
                status="unused",
                expires_at=str(card.get("autoCancelAt") or ""),
                meta=card,
            )
            update_item("redeem", params.item_id, status="used")
            return {
                "message": "兑换成功",
                "redeem_item": find_item("redeem", params.item_id),
                "card_item": card_item,
                "stats": {
                    "redeem": stats_for("redeem"),
                    "card": stats_for("card"),
                },
            }

        if provider == "988":
            url = "https://cards.779.chat/api/exchange/verify"
            resp = requests.post(url, json={"key": code}, timeout=30, verify=False)
            try:
                data = resp.json()
            except ValueError as exc:
                raise HTTPException(
                    status_code=502, detail=f"988 返回了非 JSON 响应: {(resp.text or '')[:200]}"
                ) from exc

            if not resp.ok or not data.get("success"):
                raise HTTPException(
                    status_code=resp.status_code or 502,
                    detail=data.get("message") or f"988 兑换失败({resp.status_code})",
                )

            card_info = data.get("card") or {}
            content = data.get("content") or {}
            card_number = str(
                content.get("card_number")
                or content.get("cardNumber")
                or card_info.get("card_number")
                or card_info.get("cardNumber")
                or ""
            ).strip()
            if not card_number:
                raise HTTPException(status_code=502, detail="988 返回缺少卡券信息")

            expiry = card_info.get("expires_at") or content.get("expiry_date") or ""
            card_item = add_card_item(
                value=card_number,
                provider=provider,
                status="unused",
                expires_at=str(expiry or ""),
                meta=data,
            )
            update_item("redeem", params.item_id, status="used")
            return {
                "message": "兑换成功",
                "redeem_item": find_item("redeem", params.item_id),
                "card_item": card_item,
                "stats": {
                    "redeem": stats_for("redeem"),
                    "card": stats_for("card"),
                },
            }

        raise HTTPException(status_code=501, detail="暂不支持该供应商兑换")

    @router.post("/api/card-pool/redeem-batch")
    def post_card_pool_redeem_batch(params: CardPoolRedeemBatchParams):
        validate_list_payload_limit(params.item_ids, max_items=CARD_POOL_REDEEM_BATCH_MAX_IDS, label="卡池批量兑换")
        results = []
        for item_id in params.item_ids:
            try:
                result = post_card_pool_redeem(CardPoolRedeemParams(item_id=item_id))
                results.append({"item_id": item_id, "ok": True, "result": result})
            except HTTPException as exc:
                results.append({"item_id": item_id, "ok": False, "error": exc.detail, "status_code": exc.status_code})
            except Exception as exc:
                results.append({"item_id": item_id, "ok": False, "error": str(exc), "status_code": 500})

        ok_count = sum(1 for item in results if item["ok"])
        return {
            "message": f"批量兑换完成，成功 {ok_count}/{len(results)}",
            "results": results,
        }

    @router.post("/api/card-pool/fetch-sms")
    def post_card_pool_fetch_sms(params: CardPoolFetchSmsParams):
        sms_url = (params.url or "").strip()
        if not sms_url:
            raise HTTPException(status_code=400, detail="接码 API 为空")
        if not sms_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="接码 API 格式无效")

        try:
            resp = requests.get(
                sms_url,
                timeout=20,
                verify=False,
                headers={
                    "User-Agent": "Mozilla/5.0 AutoToken/1.0",
                    "Accept": "text/plain, text/html, */*",
                },
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"请求接码接口失败: {exc}") from exc

        text = (resp.text or "").strip()
        if not resp.ok:
            raise HTTPException(
                status_code=resp.status_code or 502, detail=text[:200] or f"接码接口返回异常({resp.status_code})"
            )

        return {
            "url": sms_url,
            "status_code": resp.status_code,
            "text": text,
        }

    return router
