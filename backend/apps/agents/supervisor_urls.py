from django.urls import path

from .supervisor_api import (
    SupervisorDeployView,
    SupervisorDetailView,
    SupervisorListCreateView,
    SupervisorPublishView,
    SupervisorStatusView,
    SupervisorRunView,
)


urlpatterns = [
    path('delegates', SupervisorListCreateView.as_view(), name='delegate-list'),
    path('delegates/<int:delegate_id>', SupervisorDetailView.as_view(), name='delegate-detail'),
    path('delegates/<int:delegate_id>/publish', SupervisorPublishView.as_view(), name='delegate-publish'),
    path('delegates/<int:delegate_id>/deploy', SupervisorDeployView.as_view(), name='delegate-deploy'),
    path('delegates/<int:delegate_id>/status', SupervisorStatusView.as_view(), name='delegate-status'),
    path('delegates/<int:delegate_id>/runs', SupervisorRunView.as_view(), name='delegate-runs'),
]
