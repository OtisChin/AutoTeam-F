"""Interactive admin, main Codex, and manual account login routes."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class AdminEmailParams(BaseModel):
    email: str


class AdminSessionParams(BaseModel):
    email: str
    session_token: str


class AdminPasswordParams(BaseModel):
    password: str


class AdminCodeParams(BaseModel):
    code: str


class AdminWorkspaceParams(BaseModel):
    option_id: str


class ManualAccountCallbackParams(BaseModel):
    redirect_url: str


class ManualAccountStartParams(BaseModel):
    email: str = ""


def clean_required_code(code: str) -> str:
    cleaned = str(code or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="验证码不能为空，请输入邮件中的验证码后再提交")
    return cleaned


def create_interactive_login_router(
    *,
    playwright_lock: Any,
    playwright_executor: Any,
    current_busy_detail: Callable[[str], Any],
    logger: Any,
    admin_status: Callable[[], dict],
    main_codex_status: Callable[[], dict],
    manual_account_status: Callable[[], dict],
    get_admin_login_api: Callable[[], Any],
    get_admin_login_step: Callable[[], str | None],
    set_admin_login_state: Callable[[Any, str | None], None],
    finish_admin_login: Callable[[dict], dict],
    set_pending_admin_login: Callable[[Any, str], dict],
    get_main_codex_flow: Callable[[], Any],
    get_main_codex_step: Callable[[], str | None],
    set_main_codex_state: Callable[[Any, str | None], None],
    finish_main_codex_sync: Callable[[], dict],
    set_pending_main_codex_sync: Callable[[Any, str], dict],
    get_manual_account_flow: Callable[[], Any],
    set_manual_account_flow: Callable[[Any], None],
    finish_manual_account_flow: Callable[[dict], dict],
    set_pending_manual_account_flow: Callable[[Any, dict], dict],
) -> APIRouter:
    router = APIRouter()

    def _release_playwright_lock_if_owned() -> None:
        if playwright_lock.locked():
            playwright_lock.release()

    @router.get("/api/admin/status")
    def get_admin_status():
        """获取管理员登录状态。"""
        return admin_status()

    @router.get("/api/main-codex/status")
    def get_main_codex_status():
        """获取主号 Codex 同步状态。"""
        return main_codex_status()

    @router.get("/api/manual-account/status")
    def get_manual_account_status():
        """获取手动添加账号状态。"""
        return manual_account_status()

    @router.post("/api/admin/login/start")
    def post_admin_login_start(params: AdminEmailParams):
        """开始管理员登录流程。"""
        if get_admin_login_api():
            try:
                playwright_executor.run(get_admin_login_api().stop)
            except Exception:
                pass
            set_admin_login_state(None, None)
            _release_playwright_lock_if_owned()

        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail=current_busy_detail("有任务正在执行，请等待完成后再进行管理员登录"),
            )

        try:
            from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI

            logger.info("[API] 开始管理员登录: %s", params.email.strip())

            def _do_start(email):
                api = ChatGPTTeamAPI()
                result = api.begin_admin_login(email)
                return api, result

            api, result = playwright_executor.run(_do_start, params.email.strip())
            step = result["step"]
            logger.info("[API] 管理员登录 start 返回: step=%s detail=%s", step, result.get("detail"))
            if step == "completed":
                set_admin_login_state(api, step)
                return finish_admin_login(result)
            if step in ("password_required", "code_required", "workspace_required"):
                return set_pending_admin_login(api, step)
            playwright_executor.run(api.stop)
            _release_playwright_lock_if_owned()
            raise HTTPException(status_code=400, detail=result.get("detail") or "无法识别管理员登录步骤")
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[API] 管理员登录 start 失败")
            _release_playwright_lock_if_owned()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/admin/login/session")
    def post_admin_login_session(params: AdminSessionParams):
        """手动导入管理员 session_token。"""
        if get_admin_login_api():
            post_admin_login_cancel()

        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail=current_busy_detail("有任务正在执行，请等待完成后再导入管理员 session_token"),
            )

        try:
            from autotoken.integrations.chatgpt_api import ChatGPTTeamAPI

            logger.info("[API] 导入管理员 session_token: %s", params.email.strip())

            def _do_import(email, session_token):
                api = ChatGPTTeamAPI()
                try:
                    return api.import_admin_session(email, session_token)
                finally:
                    api.stop()

            info = playwright_executor.run(_do_import, params.email.strip(), params.session_token.strip())
            if info.get("session_token") and info.get("account_id"):
                try:
                    from autotoken.auth.codex_auth import refresh_main_auth_file

                    main_auth = playwright_executor.run(refresh_main_auth_file)
                    if main_auth:
                        info["main_auth"] = main_auth
                        logger.info("[API] session_token 导入后已刷新主号认证文件: %s", main_auth.get("auth_file"))
                except Exception as exc:
                    info["main_auth_error"] = str(exc)
                    logger.warning("[API] session_token 导入完成，但刷新主号认证文件失败: %s", exc)
            set_admin_login_state(None, None)
            return {"status": "completed", "admin": admin_status(), "info": info}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[API] 导入管理员 session_token 失败")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            _release_playwright_lock_if_owned()

    @router.post("/api/admin/login/password")
    def post_admin_login_password(params: AdminPasswordParams):
        """提交管理员密码。"""
        api = get_admin_login_api()
        if not api or get_admin_login_step() != "password_required":
            raise HTTPException(status_code=409, detail="当前没有等待密码的管理员登录流程")

        try:
            logger.info("[API] 提交管理员密码 | current_step=%s", get_admin_login_step())
            result = playwright_executor.run(api.submit_admin_password, params.password)
            step = result["step"]
            logger.info("[API] 管理员密码提交返回: step=%s detail=%s", step, result.get("detail"))
            if step == "completed":
                return finish_admin_login(result)
            if step in ("password_required", "code_required", "workspace_required"):
                set_admin_login_state(api, step)
                return {"status": step, "admin": admin_status()}
            raise HTTPException(status_code=400, detail=result.get("detail") or "管理员密码登录失败")
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[API] 管理员密码提交失败")
            try:
                playwright_executor.run(api.stop)
            except Exception:
                pass
            set_admin_login_state(None, None)
            _release_playwright_lock_if_owned()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/admin/login/code")
    def post_admin_login_code(params: AdminCodeParams):
        """提交管理员验证码。"""
        api = get_admin_login_api()
        if not api or get_admin_login_step() != "code_required":
            raise HTTPException(status_code=409, detail="当前没有等待验证码的管理员登录流程")

        try:
            code = clean_required_code(params.code)
            logger.info("[API] 提交管理员验证码 | current_step=%s code_len=%d", get_admin_login_step(), len(code))
            result = playwright_executor.run(api.submit_admin_code, code)
            step = result["step"]
            logger.info("[API] 管理员验证码提交返回: step=%s detail=%s", step, result.get("detail"))
            if step == "completed":
                return finish_admin_login(result)
            if step in ("password_required", "code_required", "workspace_required"):
                set_admin_login_state(api, step)
                return {"status": step, "admin": admin_status()}
            raise HTTPException(status_code=400, detail=result.get("detail") or "管理员验证码登录失败")
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[API] 管理员验证码提交失败")
            try:
                playwright_executor.run(api.stop)
            except Exception:
                pass
            set_admin_login_state(None, None)
            _release_playwright_lock_if_owned()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/admin/login/workspace")
    def post_admin_login_workspace(params: AdminWorkspaceParams):
        """提交管理员 workspace 选择。"""
        api = get_admin_login_api()
        if not api or get_admin_login_step() != "workspace_required":
            raise HTTPException(status_code=409, detail="当前没有等待组织选择的管理员登录流程")

        try:
            logger.info("[API] 提交管理员 workspace 选择 | option_id=%s", params.option_id)
            result = playwright_executor.run(api.select_workspace_option, params.option_id)
            step = result["step"]
            logger.info("[API] 管理员 workspace 选择返回: step=%s detail=%s", step, result.get("detail"))
            if step == "completed":
                return finish_admin_login(result)
            if step in ("password_required", "code_required", "workspace_required"):
                set_admin_login_state(api, step)
                return {"status": step, "admin": admin_status()}
            raise HTTPException(status_code=400, detail=result.get("detail") or "管理员组织选择失败")
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[API] 管理员 workspace 选择失败")
            try:
                playwright_executor.run(api.stop)
            except Exception:
                pass
            set_admin_login_state(None, None)
            _release_playwright_lock_if_owned()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/admin/login/cancel")
    def post_admin_login_cancel():
        """取消管理员登录流程。"""
        api = get_admin_login_api()
        if api:
            try:
                playwright_executor.run(api.stop)
            except Exception:
                pass
            set_admin_login_state(None, None)
            _release_playwright_lock_if_owned()
        return {"message": "管理员登录已取消", "admin": admin_status()}

    @router.post("/api/admin/logout")
    def post_admin_logout():
        """清除已保存的管理员登录态。"""
        from autotoken.settings.admin_state import clear_admin_state

        if get_admin_login_api():
            post_admin_login_cancel()
        clear_admin_state()
        return {"message": "管理员登录态已清除", "admin": admin_status()}

    @router.post("/api/main-codex/start")
    def post_main_codex_start():
        """开始主号 Codex 登录并同步到 CPA。"""
        flow = get_main_codex_flow()
        if flow:
            try:
                playwright_executor.run(flow.stop)
            except Exception:
                pass
            set_main_codex_state(None, None)
            _release_playwright_lock_if_owned()

        from autotoken.auth.codex_auth import get_saved_main_auth_file
        from autotoken.integrations.cpa_sync import sync_main_codex_to_cpa

        saved_auth_file = get_saved_main_auth_file()
        if saved_auth_file:
            sync_main_codex_to_cpa(saved_auth_file)
            return {
                "status": "completed",
                "message": "主号 Codex 已同步到 CPA",
                "codex": main_codex_status(),
                "info": {"auth_file": saved_auth_file},
            }

        if not playwright_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail=current_busy_detail("有任务正在执行，请等待完成后再同步主号 Codex"),
            )

        try:
            from autotoken.auth.codex_auth import MainCodexSyncFlow

            def _do_start():
                next_flow = MainCodexSyncFlow()
                result = next_flow.start()
                return next_flow, result

            next_flow, result = playwright_executor.run(_do_start)
            step = result["step"]
            if step == "completed":
                set_main_codex_state(next_flow, step)
                return finish_main_codex_sync()
            if step in ("password_required", "code_required"):
                return set_pending_main_codex_sync(next_flow, step)
            playwright_executor.run(next_flow.stop)
            _release_playwright_lock_if_owned()
            raise HTTPException(status_code=400, detail=result.get("detail") or "无法识别主号 Codex 登录步骤")
        except HTTPException:
            raise
        except Exception as exc:
            _release_playwright_lock_if_owned()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/main-codex/password")
    def post_main_codex_password(params: AdminPasswordParams):
        """提交主号 Codex 登录密码。"""
        flow = get_main_codex_flow()
        if not flow or get_main_codex_step() != "password_required":
            raise HTTPException(status_code=409, detail="当前没有等待密码的主号 Codex 登录流程")

        try:
            result = playwright_executor.run(flow.submit_password, params.password)
            step = result["step"]
            if step == "completed":
                return finish_main_codex_sync()
            if step in ("password_required", "code_required"):
                set_main_codex_state(flow, step)
                return {"status": step, "codex": main_codex_status()}
            raise HTTPException(status_code=400, detail=result.get("detail") or "主号 Codex 密码登录失败")
        except HTTPException:
            raise
        except Exception as exc:
            try:
                playwright_executor.run(flow.stop)
            except Exception:
                pass
            set_main_codex_state(None, None)
            _release_playwright_lock_if_owned()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/main-codex/code")
    def post_main_codex_code(params: AdminCodeParams):
        """提交主号 Codex 登录验证码。"""
        flow = get_main_codex_flow()
        if not flow or get_main_codex_step() != "code_required":
            raise HTTPException(status_code=409, detail="当前没有等待验证码的主号 Codex 登录流程")

        try:
            code = clean_required_code(params.code)
            result = playwright_executor.run(flow.submit_code, code)
            step = result["step"]
            if step == "completed":
                return finish_main_codex_sync()
            if step in ("password_required", "code_required"):
                set_main_codex_state(flow, step)
                return {"status": step, "codex": main_codex_status()}
            raise HTTPException(status_code=400, detail=result.get("detail") or "主号 Codex 验证码登录失败")
        except HTTPException:
            raise
        except Exception as exc:
            try:
                playwright_executor.run(flow.stop)
            except Exception:
                pass
            set_main_codex_state(None, None)
            _release_playwright_lock_if_owned()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/main-codex/cancel")
    def post_main_codex_cancel():
        """取消主号 Codex 登录流程。"""
        flow = get_main_codex_flow()
        if flow:
            try:
                playwright_executor.run(flow.stop)
            except Exception:
                pass
            set_main_codex_state(None, None)
            _release_playwright_lock_if_owned()
        return {"message": "主号 Codex 登录已取消", "codex": main_codex_status()}

    @router.post("/api/manual-account/start")
    def post_manual_account_start(params: ManualAccountStartParams | None = None):
        """开始手动添加账号流程，返回 OAuth 链接。"""
        params = params or ManualAccountStartParams()
        flow = get_manual_account_flow()
        if flow:
            try:
                flow.stop()
            except Exception:
                pass
            set_manual_account_flow(None)

        try:
            from autotoken.auth.manual_account import ManualAccountFlow

            next_flow = ManualAccountFlow(email=params.email, auto_open_helper=True)
            result = next_flow.start()
            return set_pending_manual_account_flow(next_flow, result)
        except HTTPException:
            raise
        except Exception as exc:
            flow = get_manual_account_flow()
            if flow:
                try:
                    flow.stop()
                except Exception:
                    pass
                set_manual_account_flow(None)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/manual-account/callback")
    def post_manual_account_callback(params: ManualAccountCallbackParams):
        """提交 OAuth 回调 URL，完成手动添加账号。"""
        flow = get_manual_account_flow()
        if not flow:
            raise HTTPException(status_code=409, detail="当前没有等待回调的手动添加账号流程")

        try:
            result = flow.submit_callback(params.redirect_url)
            return finish_manual_account_flow(result)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/manual-account/cancel")
    def post_manual_account_cancel():
        """取消手动添加账号流程。"""
        flow = get_manual_account_flow()
        if flow:
            try:
                flow.stop()
            except Exception:
                pass
            set_manual_account_flow(None)
        return {"message": "手动添加账号流程已取消", "manual_account": manual_account_status()}

    return router
