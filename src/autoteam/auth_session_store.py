import json
from pathlib import Path

from autoteam.textio import read_text, write_text

PROJECT_ROOT = Path(__file__).parent.parent.parent
AUTH_SESSION_DIR = PROJECT_ROOT / "data" / "auth_session"


def _safe_email_name(email: str) -> str:
    return (email or "").strip().lower().replace(".", "_dot_").replace("@", "@").replace("/", "_").replace("\\", "_")


def _target_path(email: str) -> Path:
    safe_name = (email or "").strip().lower().replace(".", "_").replace("@", "@")
    return AUTH_SESSION_DIR / f"{safe_name}.json"


def save_auth_session(email: str, session_data: dict) -> str:
    AUTH_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = _target_path(email)
    write_text(path, json.dumps(session_data, indent=2, ensure_ascii=False))
    return str(path)


def get_auth_session_file(email: str) -> str:
    path = _target_path(email)
    return str(path) if path.exists() else ""


def delete_auth_session(email: str) -> bool:
    path = _target_path(email)
    if not path.exists():
        return False
    path.unlink()
    return True


def load_auth_session(email: str) -> dict:
    path = _target_path(email)
    if not path.exists():
        return {}
    raw = read_text(path).strip()
    return json.loads(raw) if raw else {}


def list_auth_session_emails() -> list[str]:
    if not AUTH_SESSION_DIR.exists():
        return []
    emails = []
    for path in AUTH_SESSION_DIR.glob("*.json"):
        name = path.stem
        email = name.replace("_", ".")
        emails.append(email)
    return sorted(set(email.strip().lower() for email in emails if email.strip()))
