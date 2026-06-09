"""Trade and public plus-extractor HTTP routes."""

from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field


class TradeCreateCdkParams(BaseModel):
    quota_total: int = Field(1, validation_alias=AliasChoices("quota_total", "quotaTotal"))
    note: str = ""


class TradeRedeemParams(BaseModel):
    code: str = ""
    password: str = ""
    count: int = 1
    format: str = "cpa"
    formats: list[str] = Field(default_factory=list)


class TradeQueryParams(BaseModel):
    code: str = ""
    password: str = ""


class TradeHistoryDownloadParams(BaseModel):
    code: str = ""
    password: str = ""
    batch_id: str = Field("", validation_alias=AliasChoices("batch_id", "batchId"))


class TradeSetPasswordParams(BaseModel):
    code: str = ""
    password: str = ""


class TradeCdkStatusParams(BaseModel):
    code: str = ""


def _trade_http_error(exc: Exception):
    from autotoken.commerce.trade import TradeError

    if isinstance(exc, TradeError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_trade_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/trade/summary")
    def get_trade_summary():
        from autotoken.commerce.trade import inventory_summary

        try:
            return inventory_summary()
        except Exception as exc:
            _trade_http_error(exc)

    @router.get("/api/trade/cdks")
    def get_trade_cdks(limit: int = 200):
        from autotoken.commerce.trade import list_cdks

        try:
            return {"items": list_cdks(limit=limit)}
        except Exception as exc:
            _trade_http_error(exc)

    @router.post("/api/trade/cdks")
    def post_trade_cdk(params: TradeCreateCdkParams):
        from autotoken.commerce.trade import create_cdk

        try:
            return create_cdk(params.quota_total, note=params.note)
        except Exception as exc:
            _trade_http_error(exc)

    @router.get("/api/trade/cdks/{code}")
    def get_trade_cdk(code: str):
        from autotoken.commerce.trade import get_cdk

        try:
            return get_cdk(code)
        except Exception as exc:
            _trade_http_error(exc)

    @router.post("/api/trade/cdks/{code}/revoke")
    def post_trade_cdk_revoke(code: str):
        from autotoken.commerce.trade import revoke_cdk

        try:
            return revoke_cdk(code)
        except Exception as exc:
            _trade_http_error(exc)

    @router.get("/api/trade/cdks/{code}/redemptions/download")
    def get_trade_cdk_redemptions_download(code: str):
        from autotoken.commerce.trade import download_cdk_redemptions

        try:
            return download_cdk_redemptions(code)
        except Exception as exc:
            _trade_http_error(exc)

    @router.post("/api/public/plus-extractor/redeem")
    def post_public_plus_extractor_redeem(params: TradeRedeemParams):
        from autotoken.commerce.trade import redeem_cdk

        try:
            return redeem_cdk(params.code, params.password, params.count, params.formats or params.format)
        except Exception as exc:
            _trade_http_error(exc)

    @router.post("/api/public/plus-extractor/query")
    def post_public_plus_extractor_query(params: TradeQueryParams):
        from autotoken.commerce.trade import query_cdk_remaining

        try:
            return query_cdk_remaining(params.code, params.password)
        except Exception as exc:
            _trade_http_error(exc)

    @router.post("/api/public/plus-extractor/history")
    def post_public_plus_extractor_history(params: TradeQueryParams):
        from autotoken.commerce.trade import list_cdk_redemption_history

        try:
            return list_cdk_redemption_history(params.code, params.password)
        except Exception as exc:
            _trade_http_error(exc)

    @router.post("/api/public/plus-extractor/history/download")
    def post_public_plus_extractor_history_download(params: TradeHistoryDownloadParams):
        from autotoken.commerce.trade import download_cdk_redemption_batch

        try:
            return download_cdk_redemption_batch(params.code, params.password, params.batch_id)
        except Exception as exc:
            _trade_http_error(exc)

    @router.post("/api/public/plus-extractor/set-password")
    def post_public_plus_extractor_set_password(params: TradeSetPasswordParams):
        from autotoken.commerce.trade import set_cdk_password

        try:
            return set_cdk_password(params.code, params.password)
        except Exception as exc:
            _trade_http_error(exc)

    @router.post("/api/public/plus-extractor/cdk-status")
    def post_public_plus_extractor_cdk_status(params: TradeCdkStatusParams):
        from autotoken.commerce.trade import public_cdk_status

        try:
            return public_cdk_status(params.code)
        except Exception as exc:
            _trade_http_error(exc)

    return router
