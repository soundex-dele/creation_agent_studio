"""
App configuration for conversations app.
"""
from django.apps import AppConfig


class ConversationsConfig(AppConfig):
    """
    Configuration for the conversations app.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.conversations'
    verbose_name = 'Conversations'

    def ready(self):
        """
        Import signal handlers when the app is ready.
        """
        import apps.conversations.signals  # noqa: F401
