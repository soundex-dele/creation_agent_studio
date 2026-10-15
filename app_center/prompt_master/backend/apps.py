from django.apps import AppConfig


class PromptMasterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.prompt_master.backend"
    label = "prompt_master"
    verbose_name = "提示词大师"
