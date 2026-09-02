from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
source = (root / "src/autotoken/api_routes/account_overview.py").read_text(encoding="utf-8")
missing = [field for field in ("two_factor_enabled", "totp_status") if f'"{field}",' not in source]
if missing:
    print(f"FEATURE_CHECK_FAIL missing={','.join(missing)}")
    raise SystemExit(1)
print("FEATURE_CHECK_PASS fields=two_factor_enabled,totp_status")
