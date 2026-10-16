from django.apps import AppConfig


class CommunityChatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app_center.community_chat.backend'
    label = 'community_chat'
    verbose_name = '社区聊天'

    def ready(self):
        from . import checks  # noqa: F401
