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


def test_batch_access_preserves_fallback_overlap_and_fail_closed(monkeypatch):
    from modules.platform_api.extensions import ApplicationContributions

    runs = [SimpleNamespace(pk="one"), SimpleNamespace(pk="two")]
    fallback = Mock(return_value=False)
    bulk = ApplicationContributions(run_access=fallback, run_access_many=lambda *_: {"one": True})
    monkeypatch.setattr(extensions, "contributions", lambda: [bulk])
    assert extensions.run_access_many(object(), runs) == {"one": True, "two": False}
    assert fallback.call_count == 1
    assert fallback.call_args.args[1] is runs[1]
    other_policy = ApplicationContributions(run_access=lambda *_: False)
    monkeypatch.setattr(extensions, "contributions", lambda: [bulk, other_policy])
    assert extensions.run_access_many(object(), runs) == {"one": False, "two": False}
    broken = ApplicationContributions(run_access_many=Mock(side_effect=RuntimeError("unavailable")))
    monkeypatch.setattr(extensions, "contributions", lambda: [bulk, broken])
    assert extensions.run_access_many(object(), runs) == {"one": False, "two": False}


def test_history_input_projection_requires_every_policy_to_opt_in(monkeypatch):
    from modules.platform_api.extensions import ApplicationContributions

    provider = ApplicationContributions(run_access=lambda *_: True, run_access_input_keys=("task_id",))
    unused = ApplicationContributions(knowledge_context=lambda *_: {})
    monkeypatch.setattr(extensions, "contributions", lambda: [provider, unused])
    assert extensions.run_access_input_keys() == ("task_id",)
    legacy = ApplicationContributions(run_access=lambda *_: None)
    monkeypatch.setattr(extensions, "contributions", lambda: [provider, legacy])
    assert extensions.run_access_input_keys() is None


def test_conversation_access_failures_do_not_fall_through(monkeypatch):
    from modules.platform_api.extensions import ApplicationContributions
    from rest_framework.exceptions import PermissionDenied
    denied = Mock(side_effect=PermissionDenied('revoked document sharing'))
    monkeypatch.setattr(extensions, 'contributions', lambda: [ApplicationContributions(conversation_access=denied)])
    with pytest.raises(PermissionDenied):
        extensions.check_conversation_access(object(), object())
    monkeypatch.setattr(extensions, 'contributions', Mock(side_effect=ImportError('provider unavailable')))
    with pytest.raises(ImportError):
        extensions.check_conversation_access(object(), object())


def test_brand_reference_requires_exactly_one_provider(monkeypatch):
    from modules.platform_api.extensions import ApplicationContributions
    from modules.platform_api.branding import BrandReferenceSerializer
    from rest_framework.exceptions import ValidationError
    provider = ApplicationContributions(validate_brand_reference=lambda data: {'validated': data},
                                        brand_reference_fields=lambda: {})
    for providers in ([], [provider, provider]):
        monkeypatch.setattr(extensions, 'contributions', lambda: providers)
        with pytest.raises(ValidationError):
            BrandReferenceSerializer(data={'profile_id': 'bad'}).is_valid(raise_exception=True)
    monkeypatch.setattr(extensions, 'contributions', lambda: [provider])
    serializer = BrandReferenceSerializer(data={'profile_id': 'example'})
    assert serializer.is_valid()
    assert serializer.validated_data == {'validated': {'profile_id': 'example'}}


def test_every_private_application_registers_its_own_access_policy():
    from importlib import import_module
    from django.conf import settings
    from apps.applications.app_center.discovery import discover_packages
    expected = {'ai-drawing', 'animation-studio', 'documents', 'douyin-benchmark',
                'meeting-assistant', 'project-promotion', 'prompt-master',
                'rental-growth-assistant', 'repo-explainer', 'research-assistant'}
    packages, _ = discover_packages(settings.APP_CENTER_ROOT)
    found = set()
    for package in packages:
        if package.manifest.metadata.id not in expected:
            continue
        module, attr = package.manifest.spec.backend.extensions.rsplit('.', 1)
        assert callable(getattr(import_module(module), attr).run_access)
        found.add(package.manifest.metadata.id)
    assert found == expected


def test_brand_reference_preserves_its_public_field_schema():
    from modules.platform_api.branding import BrandReferenceSerializer
    from rest_framework import serializers
    fields = BrandReferenceSerializer().fields
    assert set(fields) == {'profile_id', 'modules', 'product_ids', 'example_ids'}
    assert isinstance(fields['profile_id'], serializers.UUIDField)
    assert fields['modules'].max_length == 5
    assert fields['product_ids'].max_length == 100


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
