from django.apps import AppConfig


class WechatAssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.wechat_assistant.backend"
    label = "wechat_assistant"
    verbose_name = "微信助手"
