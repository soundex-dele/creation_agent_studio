from django.urls import path
from . import views

prefix = "applications/<int:application_id>/wechat-assistant/"
urlpatterns = [
    path(prefix, views.StatusView.as_view(), name="wechat-status"),
    path(prefix + "agents", views.AgentsView.as_view(), name="wechat-agents"),
    path(prefix + "login", views.LoginView.as_view(), name="wechat-login"),
    path(prefix + "verify", views.VerifyView.as_view(), name="wechat-verify"),
    path(prefix + "reconnect", views.ReconnectView.as_view(), name="wechat-reconnect"),
    path(prefix + "unbind", views.UnbindView.as_view(), name="wechat-unbind"),
    path(prefix + "new-conversation", views.NewConversationView.as_view(), name="wechat-new-conversation"),
    path(prefix + "tasks", views.TasksView.as_view(), name="wechat-tasks"),
]
