"""一次性清理:把 Team 里仍然挂着但本地已经 PERSONAL 的遗留成员强踢干净。

背景:fill-personal 过去因 remove_from_team "already_absent" 误判(OpenAI /users 同步
延迟导致 GET 没返回新成员),跳过了 DELETE,结果账号在 Team 里留成 Member。运行本脚本
一键清理。使用新版 remove_from_team(带 retry),同时打印结果以便核对。

用法: uv run python scripts/sweep_leftover_members.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 注册表里 PERSONAL 状态但 Team 里还挂着的 4 个号(来自截图)
TARGETS = [
    "1fcf5e71a1@uuhfn.asia",
    "d9d6bb32c5@uuhfn.asia",
    "91006bdbbb@uuhfn.asia",
    "7e0f3205f9@uuhfn.asia",
]


def main() -> int:
    # 让脚本无论从哪里起都能 import autoteam
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "src"))

    from autoteam.chatgpt_api import ChatGPTTeamAPI
    from autoteam.manager import remove_from_team

    api = ChatGPTTeamAPI()
    api.start()
    results: dict[str, str] = {}
    try:
        for email in TARGETS:
            try:
                status = remove_from_team(api, email, return_status=True)
            except Exception as exc:
                status = f"exception: {exc}"
            results[email] = str(status)
            print(f"[sweep] {email} → {status}")
    finally:
        api.stop()

    print("\n=== 清理汇总 ===")
    for email, status in results.items():
        print(f"  {email:40s} → {status}")
    failed = [e for e, s in results.items() if s not in ("removed", "already_absent")]
    if failed:
        print(f"\n失败 {len(failed)} 个,需手动处理: {failed}")
        return 1
    print("\n全部清理完成。请刷新 ChatGPT Team Members 页面确认 Team 只剩主号 + baseline。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
