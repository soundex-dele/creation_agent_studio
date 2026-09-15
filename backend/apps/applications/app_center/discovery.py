from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from modules.catalog.definition import validate_application_definition

from .schema import ApplicationPackageManifest


class AppCenterError(ValueError):
    def __init__(self, path: Path, message: str):
        self.path = path
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class DiscoveredPackage:
    directory: Path
    manifest_path: Path
    manifest: ApplicationPackageManifest
    content_hash: str


def _load_manifest(path: Path) -> tuple[ApplicationPackageManifest, str]:
    try:
        raw = path.read_bytes()
        data = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as exc:
        raise AppCenterError(path, str(exc)) from exc
    if not isinstance(data, dict):
        raise AppCenterError(path, "manifest root must be an object")
    try:
        manifest = ApplicationPackageManifest.model_validate(data)
        definition = validate_application_definition(manifest.spec.definition)
    except (ValidationError, ValueError) as exc:
        raise AppCenterError(path, str(exc)) from exc
    if definition.kind != manifest.spec.application_kind:
        raise AppCenterError(path, "spec.application_kind must match definition.kind")
    digest = hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return manifest, digest


def discover_packages(root: Path, *, strict: bool = True) -> tuple[list[DiscoveredPackage], list[AppCenterError]]:
    root = Path(root).resolve()
    packages: list[DiscoveredPackage] = []
    errors: list[AppCenterError] = []
    if not root.exists():
        error = AppCenterError(root, "app center directory does not exist")
        if strict:
            raise error
        return [], [error]

    seen_ids: dict[str, Path] = {}
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or directory.name.startswith((".", "_")):
            continue
        manifest_path = directory / "application.yaml"
        if not manifest_path.is_file():
            errors.append(AppCenterError(directory, "application.yaml is required"))
            continue
        try:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", directory.name):
                raise AppCenterError(directory, "directory name must be a Python-safe snake_case name")
            manifest, digest = _load_manifest(manifest_path)
            module_prefix = f"app_center.{directory.name}."
            for field_name in ("django_app", "install_hook", "urlconf", "executor_entrypoint"):
                dotted_path = getattr(manifest.spec.backend, field_name)
                if dotted_path and not dotted_path.startswith(module_prefix):
                    raise AppCenterError(
                        manifest_path,
                        f"spec.backend.{field_name} must resolve inside {module_prefix}",
                    )
            for frontend in manifest.spec.frontends:
                relative_path = frontend.entrypoint or frontend.directory
                if not relative_path:
                    continue
                candidate = (directory / relative_path).resolve()
                if directory not in candidate.parents or not candidate.exists():
                    raise AppCenterError(
                        manifest_path,
                        f"frontend {frontend.id!r} path must exist inside the package",
                    )
            package_id = manifest.metadata.id
            if package_id in seen_ids:
                raise AppCenterError(
                    manifest_path,
                    f"duplicate package id {package_id!r}; first declared by {seen_ids[package_id]}",
                )
            seen_ids[package_id] = manifest_path
            packages.append(DiscoveredPackage(directory, manifest_path, manifest, digest))
        except AppCenterError as exc:
            errors.append(exc)

    if errors and strict:
        raise AppCenterError(root, "\n".join(str(error) for error in errors))
    return packages, errors


def discover_django_apps(root: Path) -> list[str]:
    packages, _ = discover_packages(root, strict=False)
    django_apps = []
    for package in packages:
        dotted_path = package.manifest.spec.backend.django_app
        if not dotted_path:
            continue
        try:
            module_name, class_name = dotted_path.rsplit(".", 1)
            getattr(importlib.import_module(module_name), class_name)
        except (ImportError, AttributeError, ValueError):
            # Keep Django bootable so validate_app_center can report the bad package.
            continue
        django_apps.append(dotted_path)
    return django_apps


def discover_executor_adapters(root: Path) -> dict[str, dict[str, str]]:
    packages, _ = discover_packages(root, strict=False)
    adapters: dict[str, dict[str, str]] = {}
    for package in packages:
        entrypoint = package.manifest.spec.backend.executor_entrypoint
        if not entrypoint:
            continue
        definition = package.manifest.spec.definition
        kind = str(definition["executor_kind"])
        key = str(definition["executor_key"])
        existing = adapters.setdefault(kind, {}).setdefault(key, entrypoint)
        if existing != entrypoint:
            raise AppCenterError(package.manifest_path, f"duplicate executor {kind}/{key}")
    return adapters


def app_center_registry_hash(root: Path) -> str:
    packages, errors = discover_packages(root, strict=False)
    snapshot = {
        "packages": {
            package.manifest.metadata.id: package.content_hash
            for package in packages
        },
        "errors": sorted(str(error) for error in errors),
    }
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
