from django.apps import AppConfig


class RentalGrowthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app_center.rental_growth_assistant.backend'
    label = 'rental_growth'
    verbose_name = '租房获客助手'
