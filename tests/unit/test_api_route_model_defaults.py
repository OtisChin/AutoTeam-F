import ast
from pathlib import Path

from autotoken.api_routes.account_cpa_auths import AccountCpaAuthImportParams, AccountSessionCpaConvertParams
from autotoken.api_routes.account_exports import AccountCredentialExportParams
from autotoken.api_routes.account_hub import AccountHubIngestPayload
from autotoken.api_routes.account_register_task import ManualRegisterParams
from autotoken.api_routes.payment_task_models import GoPayBindTaskParams


def test_api_route_model_collection_defaults_are_instance_local():
    first_hub_payload = AccountHubIngestPayload()
    second_hub_payload = AccountHubIngestPayload()
    first_hub_payload.source["node"] = "primary"
    first_hub_payload.accounts.append({"email": "one@example.com"})
    first_hub_payload.auths.append({"email": "one@example.com"})
    first_hub_payload.auth_sessions.append({"email": "one@example.com"})

    assert second_hub_payload.source == {}
    assert second_hub_payload.accounts == []
    assert second_hub_payload.auths == []
    assert second_hub_payload.auth_sessions == []

    route_models = [
        (AccountCredentialExportParams, "emails", "one@example.com"),
        (AccountCpaAuthImportParams, "files", {"filename": "auth.json", "content": "{}"}),
        (AccountSessionCpaConvertParams, "emails", "one@example.com"),
        (ManualRegisterParams, "domains", "example.com"),
        (GoPayBindTaskParams, "account_emails", "one@example.com"),
    ]

    for model_class, field_name, sample_value in route_models:
        first = model_class()
        second = model_class()
        getattr(first, field_name).append(sample_value)

        assert getattr(second, field_name) == []


def test_api_route_functions_do_not_construct_defaults_at_definition_time():
    project_root = Path(__file__).resolve().parents[2]
    route_root = project_root / "src" / "autotoken" / "api_routes"
    offenders = []

    for path in sorted(route_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            defaults = [*node.args.defaults, *node.args.kw_defaults]
            for default in defaults:
                if isinstance(default, ast.Call):
                    relative = path.relative_to(project_root)
                    offenders.append(f"{relative}:{node.lineno} {node.name}")

    assert offenders == []
