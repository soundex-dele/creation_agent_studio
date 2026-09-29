from django.apps import AppConfig


class AnimationStudioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.animation_studio.backend"
    label = "animation_studio"
    verbose_name = "动画制作"
