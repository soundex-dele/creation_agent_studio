"""
URLs for users app.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('mode/', views.auth_mode_view, name='auth_mode'),
    path('license/login/', views.license_login_view, name='license_login'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('admin/users/', views.AdminUserListCreateView.as_view(), name='admin_users'),
    path(
        'admin/users/export/',
        views.AdminUserExportView.as_view(),
        name='admin_users_export',
    ),
    path(
        'admin/users/import-template/',
        views.AdminUserImportTemplateView.as_view(),
        name='admin_users_import_template',
    ),
    path(
        'admin/users/import/',
        views.AdminUserImportView.as_view(),
        name='admin_users_import',
    ),
    path(
        'admin/users/<int:pk>/',
        views.AdminUserDetailView.as_view(),
        name='admin_user_detail',
    ),
    path('login/', views.CustomTokenObtainPairView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('token/refresh/', views.BrowserTokenRefreshView.as_view(), name='token_refresh'),
    path('me/', views.UserProfileView.as_view(), name='user_profile'),
    path('me/change-password/', views.ChangePasswordView.as_view(), name='change_password'),
    path('me/generate-api-key/', views.GenerateApiKeyView.as_view(), name='generate_api_key'),
    path('me/api-keys/', views.ApiKeyListView.as_view(), name='api_keys'),
    path('me/api-keys/<uuid:key_id>/revoke/', views.ApiKeyRevokeView.as_view(), name='revoke_api_key'),
]
