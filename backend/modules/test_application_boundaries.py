"""Executable ownership rules for the first migrated application packages."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATED = ('kitchen_assistant', 'douyin_benchmark')


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module or ''
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def production_python(directory):
    return (path for path in directory.rglob('*.py')
            if not any(part in ('tests', 'migrations') for part in path.parts)
            and not path.name.startswith('test'))


def test_migrated_backends_only_import_public_platform_capabilities():
    violations = []
    for package in MIGRATED:
        for path in production_python(ROOT / 'app_center' / package):
            for module in imports(path):
                if module.startswith(('core.', 'apps.', 'modules.')) and not module.startswith('modules.platform_api.'):
                    violations.append(f'{path.relative_to(ROOT)}: {module}')
                if module.startswith('app_center.') and not module.startswith(f'app_center.{package}.') and module != 'app_center.brand_library.public':
                    violations.append(f'{path.relative_to(ROOT)}: {module}')
    assert not violations, '\n'.join(violations)


def test_platform_application_dependencies_can_only_shrink():
    baseline = json.loads(Path(__file__).with_name('application_boundary_baseline.json').read_text())
    violations = []
    for directory in ('apps', 'modules', 'core'):
        for path in production_python(ROOT / 'backend' / directory):
            for module in imports(path):
                if not module.startswith('app_center.'):
                    continue
                if module not in baseline.get(path.relative_to(ROOT).as_posix(), []):
                    violations.append(f'{path.relative_to(ROOT)}: {module}')
                assert not any(module.startswith(f'app_center.{package}.') for package in MIGRATED)
    assert not violations, '\n'.join(violations)


def test_migrated_frontends_cannot_reach_platform_or_other_app_internals():
    violations = []
    for package in MIGRATED:
        directory = ROOT / 'app_center' / package / 'frontend'
        for path in directory.rglob('*'):
            if path.suffix not in ('.ts', '.tsx') or '__tests__' in path.parts:
                continue
            for module in re.findall(r'''(?:from\s+|import\s*\(\s*|import\s*)['"]([^'"]+)''', path.read_text(encoding='utf-8')):
                if module.startswith('@/') or (module.startswith('@applications/') and not module.startswith(f'@applications/{package}/')):
                    violations.append(f'{path.relative_to(ROOT)}: {module}')
                if module.startswith('.') and not (path.parent / module).resolve().is_relative_to(directory.parent):
                    violations.append(f'{path.relative_to(ROOT)}: {module}')
    assert not violations, '\n'.join(violations)


def test_legacy_frontend_renderer_table_can_only_shrink():
    baseline = json.loads(Path(__file__).with_name('application_boundary_baseline.json').read_text())
    source = (ROOT / 'frontend/src/lib/applicationCatalog.ts').read_text(encoding='utf-8')
    keys = {quoted or bare for quoted, bare in re.findall(r"^  (?:'([^']+)'|(\w+)):", source, re.M)}
    assert keys <= set(baseline['frontend_legacy_renderers'])
