from rest_framework.routers import DefaultRouter

from .views import (
    AuditLogViewSet, AutomationTriggerViewSet, ConnectorViewSet,
    EvaluationSuiteViewSet, GovernancePolicyViewSet, IdentityProviderViewSet, OrganizationViewSet,
    ProviderConfigViewSet, QuotaViewSet, RunTraceViewSet,
    SecretReferenceViewSet, UsageViewSet,
    DeploymentContextView, PublicIdentityDiscoveryView, ScimUserDetailView,
    ScimUsersView,
)
from .sso import OidcCallbackView, OidcLoginView, SsoExchangeView

router = DefaultRouter()
router.register('organizations', OrganizationViewSet, basename='organizations')
router.register('providers', ProviderConfigViewSet, basename='providers')
router.register('secrets', SecretReferenceViewSet, basename='secrets')
router.register('identity-providers', IdentityProviderViewSet, basename='identity-providers')
router.register('governance', GovernancePolicyViewSet, basename='governance')
router.register('connectors', ConnectorViewSet, basename='connectors')
router.register('automations', AutomationTriggerViewSet, basename='automations')
router.register('evaluations', EvaluationSuiteViewSet, basename='evaluations')
router.register('audit-logs', AuditLogViewSet, basename='audit-logs')
router.register('traces', RunTraceViewSet, basename='traces')
router.register('usage', UsageViewSet, basename='usage')
router.register('quota', QuotaViewSet, basename='quota')

urlpatterns = router.urls
urlpatterns += [__import__('django.urls', fromlist=['path']).path(
    'deployment-context/', DeploymentContextView.as_view(), name='deployment-context'),
    __import__('django.urls', fromlist=['path']).path(
    'scim/v2/Users', ScimUsersView.as_view(), name='scim-users'),
    __import__('django.urls', fromlist=['path']).path(
        'scim/v2/Users/<int:user_id>', ScimUserDetailView.as_view(),
        name='scim-user-detail'),
    __import__('django.urls', fromlist=['path']).path(
        'sso/oidc/<int:provider_id>/login', OidcLoginView.as_view(), name='oidc-login'),
    __import__('django.urls', fromlist=['path']).path(
        'sso/oidc/<int:provider_id>/callback', OidcCallbackView.as_view(), name='oidc-callback'),
    __import__('django.urls', fromlist=['path']).path(
        'sso/exchange', SsoExchangeView.as_view(), name='sso-exchange'),
    __import__('django.urls', fromlist=['path']).path(
        'sso/discovery', PublicIdentityDiscoveryView.as_view(), name='sso-discovery'),
]
