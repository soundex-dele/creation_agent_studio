from django.urls import path
from . import views
from .relay import proxy

local_patterns = [
    path("", views.LocalConfigView.as_view()),
    path("context/", views.LocalContextView.as_view()),
    path("<str:action>/", views.LocalActionView.as_view()),
]

relay_patterns = [
    path("pairings/", views.PairingView.as_view()),
    path("claim/", views.ClaimView.as_view()),
    path("connector/<uuid:device_id>/", views.ConnectorControlView.as_view()),
    path("devices/", views.DeviceListView.as_view()),
    path("devices/<uuid:device_id>/", views.DeviceView.as_view()),
    path("devices/<uuid:device_id>/proxy/<path:target>", proxy),
]
