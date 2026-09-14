from functools import lru_cache

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.module_loading import import_string


@lru_cache(maxsize=1)
def catalog_domain_port():
    adapter_path = getattr(
        settings,
        "CATALOG_DOMAIN_PORT",
        "apps.applications.catalog_port.DjangoCatalogDomainPort",
    )
    return import_string(adapter_path)()


@receiver(setting_changed)
def _clear_catalog_domain_port(*, setting, **_kwargs):
    if setting == "CATALOG_DOMAIN_PORT":
        catalog_domain_port.cache_clear()
