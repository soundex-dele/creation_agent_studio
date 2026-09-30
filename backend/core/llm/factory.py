"""Django-side factories for pluggable agent and media providers."""
from __future__ import annotations

from core.observability import log_operation

from django.conf import settings

from core.agent_engine import AgentEngine, ImageConfig
from core.agent_engine.image_provider import ImageProvider


@log_operation
def build_agent_engine(
    organization=None,
    model: str = '',
    adapter_name: str = '',
    working_directory: str = '',
) -> AgentEngine:
    """Construct the configured synchronous agent facade."""
    selected_adapter = (adapter_name or settings.AGENT_ENGINE_ADAPTER).strip().lower()
    if organization is not None and selected_adapter == 'graphflow':
        from apps.enterprise.services import resolve_provider
        routed = resolve_provider(organization, model)
        if routed:
            provider = routed['provider']
            return AgentEngine(
                api_key=routed['api_key'], base_url=provider.base_url,
                model=routed['model'] or settings.GRAPHFLOW_MODEL,
                adapter_name=selected_adapter,
                working_directory=working_directory,
            )
    return AgentEngine(
        adapter_name=selected_adapter,
        model=model or None,
        working_directory=working_directory,
    )


@log_operation
def build_image_provider() -> ImageProvider | None:
    """Construct an image-generation provider from Django settings.

    Returns ``None`` when ``IMAGE_API_KEY`` is empty so callers can surface a
    clear "service not configured" error instead of failing on a 401 upstream.
    """
    if not settings.IMAGE_API_KEY:
        return None
    return ImageProvider(ImageConfig(
        api_key=settings.IMAGE_API_KEY,
        base_url=settings.IMAGE_BASE_URL,
        model=settings.IMAGE_MODEL,
        size=settings.IMAGE_SIZE,
        quality=settings.IMAGE_QUALITY,
    ))
