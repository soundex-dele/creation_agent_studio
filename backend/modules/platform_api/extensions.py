"""Typed contributions supported by the trusted application host."""
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ApplicationContributions:
    run_access: Callable[[Any, Any], bool | None] | None = None
    knowledge_context: Callable[[Any], dict] | None = None
    case_navigation: Callable[[Any, Any], dict | None] | None = None
    case_targets: Callable[[str, Any, Any], list | None] | None = None
    dispatch_scheduled: Callable[[], None] | None = None
    conversation_access: Callable[[Any, Any], Any] | None = None
    conversation_queryset: Callable[[Any], Any] | None = None
    prepare_conversation_message: Callable[[Any, Any, str, Any], str] | None = None
    validate_brand_reference: Callable[[Any], dict] | None = None
    brand_reference_fields: Callable[[], dict] | None = None
    resolve_brand_snapshot: Callable[..., dict] | None = None
    compose_brand_snapshot: Callable[..., dict] | None = None
