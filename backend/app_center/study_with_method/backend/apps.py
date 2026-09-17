from django.apps import AppConfig


class StudyWithMethodConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.study_with_method.backend"
    label = "study_with_method"
    verbose_name = "学之有道"
