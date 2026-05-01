from pathlib import Path
from uuid import uuid4

from autoteam import bind_audit


def test_record_and_list_bind_audits(monkeypatch):
    audit_file = Path(".verify") / f"bind_audit_test_{uuid4().hex}.json"
    try:
        monkeypatch.setattr(bind_audit, "BIND_AUDIT_FILE", audit_file)

        bind_audit.record_bind_audit({"task_id": "task-1", "status": "success"})
        bind_audit.record_bind_audit({"task_id": "task-2", "status": "failed"})

        items = bind_audit.list_bind_audits(limit=10)

        assert [item["task_id"] for item in items] == ["task-2", "task-1"]
        assert all(item.get("timestamp") for item in items)
    finally:
        audit_file.unlink(missing_ok=True)


def test_bind_audit_preserves_billing_info(monkeypatch):
    audit_file = Path(".verify") / f"bind_audit_test_{uuid4().hex}.json"
    try:
        monkeypatch.setattr(bind_audit, "BIND_AUDIT_FILE", audit_file)

        bind_audit.record_bind_audit(
            {
                "task_id": "task-gopay-1",
                "flow": "gopay",
                "billing_info": {
                    "name": "John Smith",
                    "country": "US",
                    "state": "MI",
                    "city": "MUSKEGON",
                    "zip": "49442",
                    "address1": "570 MARGARET ST",
                    "address2": "APT C",
                },
            }
        )

        items = bind_audit.list_bind_audits(limit=10)

        assert items[0]["billing_info"]["name"] == "John Smith"
        assert items[0]["billing_info"]["address1"] == "570 MARGARET ST"
    finally:
        audit_file.unlink(missing_ok=True)
