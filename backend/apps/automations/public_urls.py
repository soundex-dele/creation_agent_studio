from django.urls import path

from .views import AutomationWebhookView


urlpatterns = [
    path("automations/<uuid:public_id>", AutomationWebhookView.as_view(), name="automation-webhook"),
]
