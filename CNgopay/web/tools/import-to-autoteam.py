from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "error": "usage: import-to-autoteam.py <autoteam-root> <payload.json>"}))
        return 2

    root = Path(sys.argv[1]).resolve()
    payload_path = Path(sys.argv[2]).resolve()
    sys.path.insert(0, str(root / "src"))

    from autoteam.accounts import ACCOUNT_TYPE_PLUS, SEAT_CODEX, STATUS_PLUS, update_account
    from autoteam.cpa_sync import import_local_cpa_auth_sources, update_local_auth_plan_type

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    sources = []
    selected = []
    for item in payload.get("auths") or []:
        if not isinstance(item, dict):
            continue
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        filename = str(item.get("filename") or item.get("name") or "imported.json")
        force_plus = bool(item.get("force_plus"))
        if force_plus:
            data = dict(data)
            data["plan_type"] = "plus"
            data["chatgpt_plan_type"] = "plus"
        sources.append({"name": filename, "auth_data": data})
        selected.append({"filename": filename, "force_plus": force_plus})

    result = import_local_cpa_auth_sources(sources)
    marked_plus = 0
    updated_files = []
    force_by_filename = {item["filename"]: item["force_plus"] for item in selected}

    for imported in result.get("files") or []:
        email = str(imported.get("email") or "").strip().lower()
        auth_file = str(imported.get("auth_file") or "").strip()
        filename = str(imported.get("filename") or "").strip()
        plan_type = str(imported.get("plan_type") or "").strip().lower()
        should_mark_plus = plan_type == "plus" or force_by_filename.get(filename, False)
        if not email or not auth_file or not should_mark_plus:
            continue
        plan_result = update_local_auth_plan_type(email, auth_file, plan_type="plus")
        next_auth_file = str(plan_result.get("auth_file") or auth_file)
        updated = update_account(
            email,
            status=STATUS_PLUS,
            account_type=ACCOUNT_TYPE_PLUS,
            seat_type=SEAT_CODEX,
            auth_file=next_auth_file,
            last_bind_status="plus_done",
            last_bind_provider="gopay",
            last_bind_at=time.time(),
        )
        if updated:
            marked_plus += 1
            updated_files.append({"email": email, "auth_file": next_auth_file})

    result["marked_plus"] = marked_plus
    result["updated_plus_files"] = updated_files
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
