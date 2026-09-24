from django.apps import AppConfig


class BrandLibraryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.brand_library.backend"
    label = "brand_library"
    verbose_name = "品牌资料库"
