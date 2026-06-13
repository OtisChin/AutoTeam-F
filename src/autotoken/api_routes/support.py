"""Support, sync, diagnostics, and compatibility HTTP routes."""

from collections.abc import Callable, Sequence

from fastapi import APIRouter


def create_support_router(
    *,
    log_buffer: list[dict],
    start_main_codex_sync: Callable[[], dict],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/sync")
    def post_sync():
        """Sync local auth files to CPA."""
        from autotoken.integrations.cpa_sync import sync_to_cpa

        sync_to_cpa()
        return {"message": "同步完成"}

    @router.post("/api/sync/from-cpa")
    def post_sync_from_cpa():
        """Sync auth files from CPA back to local storage."""
        from autotoken.integrations.cpa_sync import sync_from_cpa

        result = sync_from_cpa()
        return {"message": "已从 CPA 同步到本地", "result": result}

    @router.get("/api/register-failures")
    def get_register_failures_api(limit: int = 50):
        """Return recent registration/OAuth failure details."""
        from autotoken.storage.register_failures import count_by_category, list_failures

        return {
            "items": list_failures(limit=max(1, min(limit, 500))),
            "counts": count_by_category(),
        }

    @router.get("/api/logs")
    def get_logs(limit: int = 1000, since: float = 0):
        """Return recent in-memory API logs."""
        entries: Sequence[dict]
        limit = max(1, min(int(limit or 1000), 5000))
        if since > 0:
            entries = [entry for entry in log_buffer if entry["time"] > since]
        else:
            entries = log_buffer[-limit:]
        return {"logs": entries, "total": len(log_buffer)}

    @router.post("/api/sync/main-codex")
    def post_sync_main_codex():
        """Compatibility route: start main Codex login and sync to CPA."""
        return start_main_codex_sync()

    @router.get("/api/cpa/files")
    def get_cpa_files():
        """List CPA auth files."""
        from autotoken.integrations.cpa_sync import list_cpa_files

        return list_cpa_files()

    return router
