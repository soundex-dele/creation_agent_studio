from django.apps import AppConfig


class MeetingAssistantConfig(AppConfig):
    name = "app_center.meeting_assistant.backend"
    label = "meeting_assistant"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "会议与访谈助手"
