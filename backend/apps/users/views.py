"""
Views for users app.
"""
import hashlib

from django.http import HttpResponse
from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.contrib.auth import authenticate
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .serializers import (
    UserSerializer,
    UserDetailSerializer,
    RegisterSerializer,
    AdminUserSerializer,
    LoginSerializer,
    ChangePasswordSerializer
)
from core.permissions import IsAdmin
from .models import User
from .models import UserAPIKey
from .session import clear_refresh_cookie, refresh_cookie_name, set_refresh_cookie
from .licensing import (
    LicenseError,
    load_installed_license,
    machine_code,
    save_installed_license,
    validate_license,
)
from .account_transfer import (
    AccountImportError,
    account_import_template_csv,
    export_accounts_csv,
    import_accounts_csv,
)


def _session_response(user, *, response_status=status.HTTP_200_OK):
    refresh = RefreshToken.for_user(user)
    response = Response({
        'user': UserSerializer(user).data,
        'tokens': {'access': str(refresh.access_token)},
    }, status=response_status)
    return set_refresh_cookie(response, refresh)


class RegisterView(generics.CreateAPIView):
    """用户注册"""
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer
    throttle_scope = 'registration'

    def create(self, request, *args, **kwargs):
        if settings.LICENSE_AUTH_ENABLED or not settings.REGISTRATION_ENABLED:
            return Response(
                {'detail': '当前部署未开放自主注册，请联系管理员。'},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return _session_response(user, response_status=status.HTTP_201_CREATED)


class AdminUserListCreateView(generics.ListCreateAPIView):
    """List and provision accounts without reopening public registration."""

    serializer_class = AdminUserSerializer
    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = User.objects.exclude(username='system').order_by('-created_at')


class AdminUserDetailView(generics.RetrieveUpdateAPIView):
    """Allow platform administrators to delegate account capabilities."""

    serializer_class = AdminUserSerializer
    permission_classes = [IsAuthenticated, IsAdmin]
    queryset = User.objects.exclude(username='system')


def _csv_response(content, filename):
    response = HttpResponse(content, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    return response


class AdminUserExportView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, *args, **kwargs):
        content = export_accounts_csv(User.objects.exclude(username='system'))
        return _csv_response(content, 'accounts.csv')


class AdminUserImportTemplateView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, *args, **kwargs):
        return _csv_response(account_import_template_csv(), 'accounts-import-template.csv')


class AdminUserImportView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, *args, **kwargs):
        try:
            result = import_accounts_csv(request.FILES.get('file'))
        except AccountImportError as exc:
            return Response(
                {'detail': exc.detail, 'errors': exc.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(result)


class CustomTokenObtainPairView(TokenObtainPairView):
    """自定义登录视图"""
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer
    throttle_scope = 'login'

    def post(self, request, *args, **kwargs):
        if settings.LICENSE_AUTH_ENABLED:
            return Response(
                {'detail': '当前版本仅支持许可证登录'},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        user = authenticate(username=username, password=password)

        if user is None:
            return Response(
                {'detail': '用户名或密码错误'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        return _session_response(user)


@api_view(['GET'])
@permission_classes([AllowAny])
def auth_mode_view(request):
    """Expose only the public information needed to render the login page."""

    enabled = bool(settings.LICENSE_AUTH_ENABLED)
    installed = False
    if enabled:
        token = load_installed_license()
        if token:
            try:
                validate_license(token)
                installed = True
            except LicenseError:
                pass
    return Response({
        'mode': 'license' if enabled else 'account',
        'registration_enabled': bool(settings.REGISTRATION_ENABLED and not enabled),
        'machine_code': machine_code() if enabled else None,
        'license_installed': installed,
        'product': settings.LICENSE_PRODUCT_ID if enabled else None,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def license_login_view(request):
    """Validate/import an offline license and create a normal local JWT session."""

    if not settings.LICENSE_AUTH_ENABLED:
        return Response({'detail': '许可证登录未启用'}, status=status.HTTP_404_NOT_FOUND)
    supplied_token = str(request.data.get('license') or '').strip()
    token = supplied_token or load_installed_license()
    if not token:
        return Response({'detail': '请输入许可证或先导入许可证文件'},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        payload = validate_license(token)
    except LicenseError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

    username_suffix = hashlib.sha256(machine_code().encode('ascii')).hexdigest()[:16]
    with transaction.atomic():
        user, _ = User.objects.get_or_create(
            username=f'licensed-{username_suffix}',
            defaults={
                'email': f'licensed-{username_suffix}@local.invalid',
                'first_name': str(payload.get('customer') or '')[:150],
                'role': User.Role.PROFESSIONAL,
                'is_active': True,
            },
        )
        if not user.is_active:
            return Response({'detail': '本机许可证用户已被禁用'},
                            status=status.HTTP_403_FORBIDDEN)
        user.set_unusable_password()
        user.first_name = str(payload.get('customer') or '')[:150]
        user.role = User.Role.PROFESSIONAL
        user.save(update_fields=['password', 'first_name', 'role', 'updated_at'])

        from apps.enterprise.models import Membership
        from apps.enterprise.tenancy import provision_single_tenant_user

        membership = provision_single_tenant_user(user)
        if membership is None:
            return Response({'detail': '无法初始化本机工作区'},
                            status=status.HTTP_403_FORBIDDEN)
        if membership.role != Membership.Role.OWNER:
            membership.role = Membership.Role.ADMIN
            membership.save(update_fields=['role', 'updated_at'])

    if supplied_token:
        try:
            save_installed_license(token)
        except OSError:
            return Response({'detail': '许可证有效，但无法保存到本机'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return _session_response(user)


class BrowserTokenRefreshView(TokenRefreshView):
    """Rotate the browser refresh token without exposing it to JavaScript."""

    permission_classes = [AllowAny]
    throttle_scope = 'token_refresh'

    def post(self, request, *args, **kwargs):
        if settings.LICENSE_AUTH_ENABLED:
            token = load_installed_license()
            if not token:
                return Response({'detail': '本机未安装许可证'},
                                status=status.HTTP_401_UNAUTHORIZED)
            try:
                validate_license(token)
            except LicenseError as exc:
                return Response({'detail': str(exc)},
                                status=status.HTTP_401_UNAUTHORIZED)
        refresh_token = request.data.get('refresh') or request.COOKIES.get(
            refresh_cookie_name())
        if not refresh_token:
            return Response(
                {'detail': 'Refresh token is required.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        serializer = self.get_serializer(data={'refresh': refresh_token})
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        rotated_refresh = payload.pop('refresh', refresh_token)
        response = Response(payload, status=status.HTTP_200_OK)
        return set_refresh_cookie(response, rotated_refresh)


class UserProfileView(generics.RetrieveUpdateAPIView):
    """用户信息"""
    serializer_class = UserDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(generics.UpdateAPIView):
    """修改密码"""
    serializer_class = ChangePasswordSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = self.get_object()
        old_password = serializer.validated_data['old_password']
        new_password = serializer.validated_data['new_password']

        if not user.check_password(old_password):
            return Response(
                {'old_password': '旧密码错误'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save()

        return Response({'detail': '密码修改成功'})


class GenerateApiKeyView(generics.GenericAPIView):
    """生成 API 密钥"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        name = str(request.data.get('name') or 'default')[:100]
        scopes = request.data.get('scopes') or []
        if not isinstance(scopes, list):
            return Response({'scopes': 'Must be a list.'}, status=status.HTTP_400_BAD_REQUEST)
        expires_at = request.data.get('expires_at')
        if expires_at:
            expires_at = parse_datetime(str(expires_at))
            if expires_at is None or expires_at <= timezone.now():
                return Response({'expires_at': 'Use a future ISO-8601 datetime.'},
                                status=status.HTTP_400_BAD_REQUEST)
        key, raw_key = UserAPIKey.issue(
            user=request.user, name=name, scopes=scopes, expires_at=expires_at)
        return Response({
            'id': str(key.id),
            'name': key.name,
            'prefix': key.prefix,
            'scopes': key.scopes,
            'expires_at': key.expires_at,
            'api_key': raw_key,
        }, status=status.HTTP_201_CREATED)


class ApiKeyListView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([{
            'id': str(key.id), 'name': key.name, 'prefix': key.prefix,
            'scopes': key.scopes, 'expires_at': key.expires_at,
            'last_used_at': key.last_used_at, 'revoked_at': key.revoked_at,
            'created_at': key.created_at,
        } for key in request.user.api_keys.all()])


class ApiKeyRevokeView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, key_id):
        from django.utils import timezone
        key = request.user.api_keys.filter(id=key_id, revoked_at__isnull=True).first()
        if key is None:
            return Response({'detail': 'API key not found.'}, status=404)
        key.revoked_at = timezone.now()
        key.save(update_fields=['revoked_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([AllowAny])
def logout_view(request):
    """登出

    AllowAny: logout must work even when the access token has expired — the
    axios interceptor calls this from its 401 handler, at which point the
    access token is already dead. We only need the refresh token from the body
    to blacklist it.
    """
    try:
        refresh_token = request.data.get('refresh') or request.COOKIES.get(
            refresh_cookie_name())
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
        return clear_refresh_cookie(Response({'detail': '登出成功'}))
    except Exception:
        return clear_refresh_cookie(Response(
            {'detail': '登出失败'}, status=status.HTTP_400_BAD_REQUEST))
