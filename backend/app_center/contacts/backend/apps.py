from django.apps import AppConfig


class ContactsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_center.contacts.backend"
    label = "contacts"
    verbose_name = "Contacts"
