from django.apps import AppConfig


class ProjectPromotionConfig(AppConfig):
    name = 'app_center.project_promotion.backend'
    label = 'project_promotion'
    verbose_name = '项目宣传助手'
    default_auto_field = 'django.db.models.BigAutoField'
