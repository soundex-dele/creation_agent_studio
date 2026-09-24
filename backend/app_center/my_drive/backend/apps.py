from django.apps import AppConfig


class MyDriveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.my_drive.backend"
    label = "my_drive"
    verbose_name = "我的网盘"
