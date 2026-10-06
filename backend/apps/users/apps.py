"""
App configuration for users app.
"""
from django.apps import AppConfig


class UsersConfig(AppConfig):
    """
    Configuration for the users app.
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'
    verbose_name = 'Users'

    def ready(self):
        """
        Import signal handlers when the app is ready.
        """
        from . import signals  # noqa: F401
