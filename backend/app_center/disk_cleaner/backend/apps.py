from django.apps import AppConfig


class DiskCleanerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.disk_cleaner.backend"
    label = "disk_cleaner"
    verbose_name = "磁盘清理大师"
