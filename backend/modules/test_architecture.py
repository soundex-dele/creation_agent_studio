"""Executable module boundaries for the modular monolith."""
import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent

# Domain integrations are explicit exceptions. Any new modules -> apps edge
# must be reviewed here instead of silently growing another dependency path.
ALLOWED_DOMAIN_IMPORTS = {
    "modules/catalog/api/views.py": {"apps.applications.models"},
    "modules/catalog/models.py": {
        "apps.agents.models",
        "apps.applications.models",
    },
    "modules/execution/api/streaming.py": {"apps.enterprise.models"},
    "modules/execution/application/projections.py": {"apps.conversations.models"},
    "modules/execution/application/start_runs.py": {
        "apps.agents.models",
        "apps.enterprise.models",
        "apps.enterprise.services",
    },
    "modules/execution/infrastructure/coordinator.py": {
        "apps.enterprise.models",
        "apps.enterprise.services",
    },
    "modules/execution/runtime/builtin.py": {"apps.enterprise.models"},
    "modules/tenancy/models.py": {"apps.enterprise.models"},
    "modules/tenancy/permissions.py": {"apps.enterprise.models"},
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
