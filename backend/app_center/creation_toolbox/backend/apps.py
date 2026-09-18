from django.apps import AppConfig


class CreationToolboxConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.creation_toolbox.backend"
    label = "creation_toolbox"
    verbose_name = "Creation Toolbox"

    def ready(self):
        from . import signals  # noqa: F401

