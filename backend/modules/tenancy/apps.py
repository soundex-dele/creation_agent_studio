from django.apps import AppConfig


class TenancyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.tenancy"
    label = "v2_tenancy"
    verbose_name = "V2 Tenancy"
