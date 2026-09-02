"""Command-line parser and dispatch for AutoToken."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autotoken",
        description="ChatGPT Token自由管理系统",
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    sub.add_parser("status", help="查看所有账号状态")
    check_p = sub.add_parser("check", help="检查活跃账号 Codex 额度")
    check_p.add_argument(
        "--include-standby",
        action="store_true",
        help="同时探测 standby 池的 quota(限速+24h 去重,会对每个 standby 账号打一次 wham/usage)",
    )
    rotate_p = sub.add_parser("rotate", help="智能轮转（检查额度 → 移出 → 复用旧号 → 万不得已才创建新号）")
    rotate_p.add_argument("target", type=int, nargs="?", default=5, help="目标成员数（默认 5）")
    sub.add_parser("add", help="手动添加一个新账号")
    sub.add_parser("manual-add", help="手动 OAuth 添加账号（打开链接登录后粘贴回调 URL）")
    admin_login_p = sub.add_parser("admin-login", help="交互式完成管理员主号登录")
    admin_login_p.add_argument("--email", help="管理员邮箱；不传则运行时交互输入")
    admin_session_p = sub.add_parser("admin-session", help="手动输入 session_token 导入管理员登录态")
    admin_session_p.add_argument("--email", help="管理员邮箱；不传则运行时交互输入")
    sub.add_parser("main-codex-sync", help="交互式同步主号 Codex 到 CPA")

    fill_p = sub.add_parser("fill", help="补满 Team 成员到指定数量")
    fill_p.add_argument("target", type=int, nargs="?", default=5, help="目标成员数（默认 5）")

    cleanup_p = sub.add_parser("cleanup", help="清理多余成员（只移除本地管理的）")
    cleanup_p.add_argument("max_seats", type=int, nargs="?", default=None, help="最大席位数")

    sub.add_parser("sync", help="手动同步认证文件到 CPA")
    sub.add_parser("pull-cpa", help="从 CPA 反向同步认证文件到本地")

    reconcile_p = sub.add_parser(
        "reconcile",
        help="对账 Team 实际成员 vs 本地状态,修复残废 / 错位 / 耗尽未抛弃 / ghost",
    )
    reconcile_p.add_argument(
        "--dry-run",
        action="store_true",
        help="只输出诊断报告,不 kick、不改 accounts.json",
    )

    api_p = sub.add_parser("api", help="启动 HTTP API 服务器")
    api_p.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    api_p.add_argument("--port", type=int, default=8787, help="监听端口（默认 8787）")
    api_p.add_argument("--build", "-b", action="store_true", help="启动前重新编译前端")
    worker_p = sub.add_parser("setup-2fa-worker", help=argparse.SUPPRESS)
    worker_p.add_argument("--emails-json", required=True)
    worker_p.add_argument("--source", default="cli")
    return parser


def run_startup_checks(command: str) -> None:
    if command not in ("api", "setup-2fa-worker"):
        from autotoken.settings.setup_wizard import check_and_setup

        check_and_setup(interactive=True)

    try:
        from autotoken.storage.auth_storage import ensure_auth_file_permissions

        ensure_auth_file_permissions()
    except Exception:
        pass


def dispatch(args: argparse.Namespace):
    from autotoken.interfaces import manager

    if args.command == "status":
        return manager.cmd_status()
    if args.command == "check":
        return manager.cmd_check(include_standby=getattr(args, "include_standby", False))
    if args.command == "rotate":
        return manager.cmd_rotate(args.target)
    if args.command == "add":
        return manager.cmd_add()
    if args.command == "manual-add":
        return manager.cmd_manual_add()
    if args.command == "admin-login":
        return manager.cmd_admin_login(args.email)
    if args.command == "admin-session":
        return manager.cmd_admin_session(args.email)
    if args.command == "main-codex-sync":
        return manager.cmd_main_codex_sync()
    if args.command == "fill":
        return manager.cmd_fill(args.target)
    if args.command == "cleanup":
        return manager.cmd_cleanup(args.max_seats)
    if args.command == "sync":
        from autotoken.integrations.cpa_sync import sync_to_cpa

        return sync_to_cpa()
    if args.command == "pull-cpa":
        return manager.cmd_pull_cpa()
    if args.command == "reconcile":
        return manager.cmd_reconcile(dry_run=getattr(args, "dry_run", False))
    if args.command == "api":
        from autotoken.interfaces.api import start_server

        return start_server(host=args.host, port=args.port, build=getattr(args, "build", False))
    if args.command == "setup-2fa-worker":
        from autotoken.services.account_two_factor_process import run_account_two_factor_worker_from_cli

        return run_account_two_factor_worker_from_cli(args)
    raise SystemExit(f"unknown command: {args.command}")


def main(argv: Sequence[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    run_startup_checks(args.command)
    return dispatch(args)
