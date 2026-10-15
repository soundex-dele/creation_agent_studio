from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.documents.backend"
    label = "online_documents"
    verbose_name = "在线文档"
