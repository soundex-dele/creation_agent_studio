from django.apps import AppConfig


class AIDrawingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.ai_drawing.backend"
    label = "ai_drawing"
    verbose_name = "AI 绘图"
