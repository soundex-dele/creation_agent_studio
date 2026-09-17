"""Executable module boundaries for the modular monolith."""
import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent

# Domain integrations are explicit exceptions. Any new modules -> apps edge
# must be reviewed here instead of silently growing another dependency path.
ALLOWED_DOMAIN_IMPORTS = {
    "modules/catalog/api/serializers.py": {"apps.applications.models"},
    "modules/catalog/api/views.py": {
        "apps.applications.models",
        "apps.enterprise.models",
    },
    "modules/execution/api/streaming.py": {"apps.enterprise.models"},
    "modules/execution/api/views.py": {"apps.enterprise.models"},
    "modules/execution/application/projections.py": {"apps.conversations.models"},
    "modules/tenancy/middleware.py": {"apps.enterprise.tenancy"},
    "modules/tenancy/permissions.py": {
        "apps.enterprise.models",
        "apps.enterprise.tenancy",
    },
    "modules/tenancy/single_tenant_urls.py": {
        "apps.applications.app_center.urls",
        "apps.automations.urls",
        "apps.enterprise.tenancy",
    },
}


def _domain_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("apps."):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(
                alias.name for alias in node.names if alias.name.startswith("apps.")
            )
    return imported


def test_shared_module_domain_dependencies_are_explicit():
    actual = {}
    for path in (BACKEND_ROOT / "modules").rglob("*.py"):
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if "/migrations/" in f"/{relative}/" or "/tests/" in f"/{relative}/":
            continue
        imports = _domain_imports(path)
        if imports:
            actual[relative] = imports
    assert actual == ALLOWED_DOMAIN_IMPORTS


def test_removed_parallel_execution_implementations_do_not_return():
    banned_fragments = (
        "class Agent" + "Execution",
        "class Workflow" + "StepRun",
        "class Workflow" + "Run",
        "agent" + "Protocol.ts",
        "sse" + "Client.ts",
        "/api/agent/" + "v2/",
        "workflow-" + "sequential",
        "_execute_workflow_" + "inline",
    )
    offenders = []
    roots = (BACKEND_ROOT / "apps", BACKEND_ROOT / "modules", REPOSITORY_ROOT / "frontend" / "src")
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            relative = path.relative_to(REPOSITORY_ROOT).as_posix()
            if "/migrations/" in f"/{relative}/" or "/tests/" in f"/{relative}/" or path == Path(__file__):
                continue
            content = path.read_text(encoding="utf-8")
            for fragment in banned_fragments:
                if fragment in content:
                    offenders.append(f"{relative}: {fragment}")
    assert not offenders, "Removed execution implementation references found:\n" + "\n".join(offenders)


def test_public_application_routes_are_versioned():
    from backend.urls import urlpatterns

    api_patterns = [
        str(pattern.pattern)
        for pattern in urlpatterns
        if str(pattern.pattern).startswith("api/")
    ]
    assert api_patterns
    assert all(pattern.startswith("api/v1/") for pattern in api_patterns)


def test_data_before_schema_migrations_are_non_atomic():
    schema_operations = (
        "migrations.AddField(",
        "migrations.RemoveField(",
        "migrations.AlterField(",
        "migrations.CreateModel(",
        "migrations.DeleteModel(",
        "migrations.AddConstraint(",
        "migrations.RemoveConstraint(",
    )
    offenders = []
    for root in (BACKEND_ROOT / "apps", BACKEND_ROOT / "modules"):
        for path in root.glob("*/migrations/*.py"):
            content = path.read_text(encoding="utf-8")
            data_position = content.find("migrations.RunPython")
            if data_position < 0:
                continue
            has_later_schema_change = any(
                content.find(operation, data_position + 1) >= 0
                for operation in schema_operations
            )
            if has_later_schema_change and "atomic = False" not in content:
                offenders.append(path.relative_to(REPOSITORY_ROOT).as_posix())
    assert not offenders, (
        "PostgreSQL can retain deferred trigger events when data and later "
        "schema changes share one migration transaction:\n" + "\n".join(offenders)
    )


def test_browser_auth_credentials_are_not_persisted():
    frontend_root = REPOSITORY_ROOT / "frontend" / "src"
    banned_fragments = ("refreshToken", "refresh_token", "tokens.refresh", "token: state.token")
    offenders = []
    for path in frontend_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        if "/__tests__/" in f"/{path.as_posix()}/":
            continue
        content = path.read_text(encoding="utf-8")
        for fragment in banned_fragments:
            if fragment in content:
                offenders.append(
                    f"{path.relative_to(REPOSITORY_ROOT).as_posix()}: {fragment}"
                )
    assert not offenders, "Browser credential persistence found:\n" + "\n".join(offenders)
