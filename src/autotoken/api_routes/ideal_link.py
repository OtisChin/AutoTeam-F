"""iDEAL link extraction HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from autotoken.integrations.gpthel_ideal import app as legacy


IdealLongLinkRequest = legacy.LongLinkRequest
IdealQrRequest = legacy.QRCodeRequest
IdealProxyChainTestRequest = legacy.ProxyChainTestRequest


def _ideal_request(params: IdealLongLinkRequest) -> IdealLongLinkRequest:
    return params.model_copy(
        update={
            "link_type": "ideal",
            "billing_country": "NL",
            "payment_locale": params.payment_locale or "nl-NL",
            "checkout_ui_mode": params.checkout_ui_mode or "hosted",
        },
        deep=True,
    )


def _ideal_proxy_request(params: IdealProxyChainTestRequest) -> IdealProxyChainTestRequest:
    return params.model_copy(update={"link_type": "ideal"}, deep=True)


def _namespaced_diagnostic_url(snapshot: dict[str, Any]) -> dict[str, Any]:
    data = dict(snapshot or {})
    diagnostic_url = str(data.get("diagnostic_url") or "").strip()
    if diagnostic_url.startswith("/api/long-link/jobs/"):
        data["diagnostic_url"] = diagnostic_url.replace("/api/long-link/jobs/", "/api/ideal/long-link/jobs/", 1)
    return data


def create_ideal_link_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/ideal/long-link/start")
    def post_ideal_long_link_start(params: IdealLongLinkRequest) -> dict[str, str]:
        try:
            return legacy.start_long_link_job(_ideal_request(params))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"iDEAL 提链任务启动失败: {exc}") from exc

    @router.get("/api/ideal/long-link/jobs/{job_id}")
    def get_ideal_long_link_job(job_id: str) -> dict[str, Any]:
        return _namespaced_diagnostic_url(legacy.job_snapshot(job_id))

    @router.get("/api/ideal/long-link/jobs/{job_id}/diagnostics")
    def get_ideal_long_link_job_diagnostics(job_id: str):
        return legacy.get_long_link_job_diagnostics(job_id)

    @router.post("/api/ideal/proxy-chain-test")
    def post_ideal_proxy_chain_test(params: IdealProxyChainTestRequest) -> dict[str, Any]:
        try:
            return legacy.proxy_chain_test(_ideal_proxy_request(params))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"iDEAL 代理测试失败: {exc}") from exc

    @router.post("/api/ideal/qr")
    def post_ideal_qr(params: IdealQrRequest):
        return legacy.qr_code(params)

    return router
