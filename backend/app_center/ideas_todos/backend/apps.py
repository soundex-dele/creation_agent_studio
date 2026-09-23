from django.apps import AppConfig


class IdeasTodosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.ideas_todos.backend"
    label = "ideas_todos"
    verbose_name = "想法&待办"
