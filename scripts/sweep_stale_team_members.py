"""一次性清理:Team 里遗留的 4 个问题号。

背景(验证后明确):
- 923b3319f9 / 58605518fa / 338d1922a9: 本地 accounts.json 标 standby,
  但 /api/team/members 证实这 3 个号实际仍在 Team 里占席位 —— 之前 rotate
  旧代码 remove_from_team 的 already_absent 误判导致 DELETE 被跳过。
- 4127a3a484: 本地 active 但 auth_file 缺失(Codex OAuth 失败留下的半成品),
  一起踢掉本地置 standby 更干净。

脚本用新版 remove_from_team(带 retry,无 already_absent 误判),直接 kick,
完了把本地状态统一置为 standby。

用法: uv run python scripts/sweep_stale_team_members.py
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGETS = [
    "923b3319f9@uuhfn.asia",
    "58605518fa@uuhfn.asia",
    "338d1922a9@uuhfn.asia",
    "4127a3a484@uuhfn.asia",
]


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "src"))

    from autoteam.accounts import STATUS_STANDBY, update_account
    from autoteam.chatgpt_api import ChatGPTTeamAPI
    from autoteam.manager import remove_from_team

    api = ChatGPTTeamAPI()
    api.start()
    results: dict[str, str] = {}
    try:
        for email in TARGETS:
            try:
                status = remove_from_team(api, email, return_status=True)
                if status in ("removed", "already_absent"):
                    update_account(email, status=STATUS_STANDBY)
            except Exception as exc:
                status = f"exception: {exc}"
            results[email] = str(status)
            print(f"[sweep-stale] {email} → {status}")
    finally:
        api.stop()

    print("\n=== 汇总 ===")
    for email, status in results.items():
        print(f"  {email:40s} → {status}")
    failed = [e for e, s in results.items() if s not in ("removed", "already_absent")]
    if failed:
        print(f"\n失败 {len(failed)} 个: {failed}")
        return 1
    print("\n全部清理完成。Team 应缩回主号 + 3 个 active 子号 = 4 席。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
