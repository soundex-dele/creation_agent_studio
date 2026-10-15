from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.applications.app_center import extensions


def test_access_requires_every_applicable_policy_and_fails_closed(monkeypatch):
    user, run = object(), object()
    monkeypatch.setattr(extensions, 'contributions', lambda: [SimpleNamespace(run_access=lambda *_: None)])
    assert extensions.run_access(user, run) is None
    monkeypatch.setattr(extensions, 'contributions', lambda: [
        SimpleNamespace(run_access=lambda *_: True), SimpleNamespace(run_access=lambda *_: False)])
    assert extensions.run_access(user, run) is False
    monkeypatch.setattr(extensions, 'contributions', Mock(side_effect=ImportError('missing provider')))
    assert extensions.run_access(user, run) is False


def test_knowledge_context_never_silently_overwrites_another_application(monkeypatch):
    monkeypatch.setattr(extensions, 'contributions', lambda: [
        SimpleNamespace(knowledge_context=lambda _: {'scope': 'first'}),
        SimpleNamespace(knowledge_context=lambda _: {'scope': 'second'}),
    ])
    with pytest.raises(ValueError, match='Conflicting'):
        extensions.knowledge_context(object())


def test_scheduler_failure_does_not_skip_other_applications(monkeypatch):
    succeeding = Mock()
    monkeypatch.setattr(extensions, 'contributions', lambda: [
        SimpleNamespace(dispatch_scheduled=Mock(side_effect=RuntimeError('offline'))),
        SimpleNamespace(dispatch_scheduled=succeeding),
    ])
    extensions.dispatch_scheduled()
    succeeding.assert_called_once_with()


def test_root_layout_preserves_python_package_identity():
    from pathlib import Path
    from django.conf import settings
    import app_center
    from backend.paths import PROJECT_ROOT
    assert settings.APP_CENTER_ROOT == PROJECT_ROOT / 'app_center'
    assert Path(app_center.__file__).resolve().parent == settings.APP_CENTER_ROOT
    assert not (PROJECT_ROOT / 'backend' / 'app_center').exists()


def test_public_artifact_capability_reuses_execution_implementation():
    from modules.platform_api.artifacts import persist_artifact, record_artifact
    from modules.execution.application.runs import record_artifact as implementation
    assert callable(persist_artifact)
    assert record_artifact is implementation


def test_custom_package_root_takes_precedence_without_changing_working_directory(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    from backend.paths import expose_app_center
    original = Path.cwd()
    monkeypatch.setattr(sys, 'path', list(sys.path))
    package = tmp_path / 'app_center'
    package.mkdir()
    assert expose_app_center(package) == package
    assert sys.path[0] == str(tmp_path)
    assert Path.cwd() == original


def test_discovery_rejects_duplicate_renderers_and_foreign_extension_paths(tmp_path):
    from pathlib import Path
    import yaml
    from django.conf import settings
    from apps.applications.app_center.discovery import AppCenterError, discover_packages
    template = yaml.safe_load((settings.APP_CENTER_ROOT / 'kitchen_assistant/application.yaml').read_text(encoding='utf-8'))
    for name in ('first', 'second'):
        directory = tmp_path / name
        (directory / 'frontend').mkdir(parents=True)
        (directory / 'frontend/index.ts').write_text('export default {};')
        template['metadata']['id'] = name
        template['spec']['backend'] = {'extensions': f'app_center.{name}.extensions.provider'}
        template['spec']['database']['mode'] = 'none'
        (directory / 'application.yaml').write_text(yaml.safe_dump(template), encoding='utf-8')
    with pytest.raises(AppCenterError, match='duplicate frontend renderer'):
        discover_packages(tmp_path)
    second = tmp_path / 'second/application.yaml'
    template['spec']['frontends'][0]['renderer_key'] = 'second'
    template['spec']['backend']['extensions'] = 'app_center.first.extensions.provider'
    second.write_text(yaml.safe_dump(template), encoding='utf-8')
    with pytest.raises(AppCenterError, match='must resolve inside'):
        discover_packages(tmp_path)
