from django.conf import settings
from django.core.checks import Error, register


@register()
def knowledge_configuration_check(app_configs, **kwargs):
    errors = []
    if int(getattr(settings, "KNOWLEDGE_EMBEDDING_DIMENSIONS", 0)) < 1:
        errors.append(Error(
            "KNOWLEDGE_EMBEDDING_DIMENSIONS must be positive.",
            id="knowledge.E001",
        ))
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        errors.append(Error(
            "sqlite-vec is required for desktop knowledge search.",
            id="knowledge.E002",
        ))
    return errors
