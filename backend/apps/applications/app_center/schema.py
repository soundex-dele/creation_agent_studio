from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_PACKAGE_ID = re.compile(r"^[a-z][a-z0-9-]*$")
_DOTTED_PATH = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")


class CategoryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    slug: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    icon: str = ""
    order: int = 0


class MetadataManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    version: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=100)
    description: str
    category: CategoryManifest
    icon: str = ""
    color: str = ""
    tags: list[str] = Field(default_factory=list)
    developer: str = "Creation Studio"

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not _PACKAGE_ID.fullmatch(value):
            raise ValueError("must be a lowercase slug")
        return value


class BackendManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    django_app: str | None = None
    install_hook: str | None = None
    urlconf: str | None = None
    executor_entrypoint: str | None = None

    @field_validator("django_app", "install_hook", "urlconf", "executor_entrypoint")
    @classmethod
    def valid_dotted_path(cls, value: str | None) -> str | None:
        if value is not None and not _DOTTED_PATH.fullmatch(value):
            raise ValueError("must be a dotted Python path")
        return value


class DatabaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["none", "django-migrations"] = "none"
    schema_version: int = Field(default=1, ge=1)
    tenant_scoped: bool = True


class InstallManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scope: Literal["per-organization"] = "per-organization"
    initial_deployment: Literal["none", "development"] = "development"


class FrontendManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=40)
    type: Literal["react", "qt"]
    renderer_key: str | None = Field(default=None, min_length=1, max_length=160)
    entrypoint: str | None = Field(default=None, min_length=1, max_length=260)
    directory: str | None = Field(default=None, min_length=1, max_length=260)
    platforms: list[Literal["windows", "linux", "macos", "web"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_variant(self):
        if self.type == "react" and not (self.renderer_key and self.directory):
            raise ValueError("react frontends require renderer_key and directory")
        if self.type == "qt" and not self.entrypoint:
            raise ValueError("qt frontends require entrypoint")
        return self


class SpecManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    application_kind: Literal["chat", "task", "custom"]
    launch_mode: Literal["run", "chat", "dedicated"]
    definition: dict[str, Any]
    backend: BackendManifest = Field(default_factory=BackendManifest)
    database: DatabaseManifest = Field(default_factory=DatabaseManifest)
    install: InstallManifest = Field(default_factory=InstallManifest)
    frontends: list[FrontendManifest] = Field(default_factory=list)

    @model_validator(mode="after")
    def database_requires_django_app(self):
        if self.database.mode == "django-migrations" and not self.backend.django_app:
            raise ValueError("database mode django-migrations requires backend.django_app")
        if self.launch_mode == "run" and not (
            self.backend.executor_entrypoint or self.definition.get("executor_key")
        ):
            raise ValueError("run applications require an executor")
        frontend_ids = [frontend.id for frontend in self.frontends]
        if len(frontend_ids) != len(set(frontend_ids)):
            raise ValueError("frontend ids must be unique")
        return self


class ApplicationPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    api_version: Literal["creation-studio/v1"]
    kind: Literal["ApplicationPackage"]
    metadata: MetadataManifest
    spec: SpecManifest
