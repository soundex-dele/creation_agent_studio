from functools import lru_cache

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.module_loading import import_string


@lru_cache(maxsize=1)
def execution_domain_port():
    """Resolve the product-domain adapter without importing product Apps here."""

    adapter_path = getattr(
        settings,
        "EXECUTION_DOMAIN_PORT",
        "apps.enterprise.execution_port.DjangoExecutionDomainPort",
    )
    return import_string(adapter_path)()


@receiver(setting_changed)
def _clear_execution_domain_port(*, setting, **_kwargs):
    if setting == "EXECUTION_DOMAIN_PORT":
        execution_domain_port.cache_clear()
