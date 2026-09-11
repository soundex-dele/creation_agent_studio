from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.catalog"
    label = "v2_catalog"
    verbose_name = "V2 Catalog"
