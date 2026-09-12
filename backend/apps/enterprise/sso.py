import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import ExternalIdentity, IdentityProvider, Membership
from .services import resolve_secret
from .tenancy import get_single_tenant_organization, single_tenant_mode_enabled


def _json(url, *, data=None, headers=None):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read(1024 * 1024))


def _discovery(provider):
    url = provider.metadata_url or f'{provider.issuer.rstrip("/")}/.well-known/openid-configuration'
    return _json(url)


def _identity_providers():
    providers = IdentityProvider.objects.select_related('organization').filter(
        protocol=IdentityProvider.Protocol.OIDC,
        is_active=True,
        organization__is_active=True,
    )
    if single_tenant_mode_enabled():
        organization = get_single_tenant_organization()
        return providers.filter(organization=organization) if organization else providers.none()
    return providers


class OidcLoginView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, provider_id):
        provider = _identity_providers().filter(id=provider_id).first()
        if provider is None:
            return Response({'detail': 'OIDC provider not found.'}, status=404)
        try:
            metadata = _discovery(provider)
        except Exception:
            return Response({'detail': 'OIDC discovery failed.'}, status=502)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        state = secrets.token_urlsafe(32)
        redirect_uri = request.build_absolute_uri(
            f'/api/enterprise/sso/oidc/{provider.id}/callback')
        cache.set(f'oidc-state:{state}', {
            'provider_id': provider.id, 'verifier': verifier,
            'redirect_uri': redirect_uri,
        }, timeout=600)
        params = {
            'response_type': 'code', 'client_id': provider.client_id,
            'redirect_uri': redirect_uri, 'scope': 'openid email profile',
            'state': state, 'nonce': secrets.token_urlsafe(24),
            'code_challenge': challenge, 'code_challenge_method': 'S256',
        }
        return redirect(f'{metadata["authorization_endpoint"]}?{urllib.parse.urlencode(params)}')


class OidcCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, provider_id):
        state = request.query_params.get('state', '')
        flow = cache.get(f'oidc-state:{state}')
        cache.delete(f'oidc-state:{state}')
        if not flow or str(flow['provider_id']) != str(provider_id):
            return Response({'detail': 'Invalid or expired OIDC state.'}, status=400)
        provider = _identity_providers().filter(id=provider_id).first()
        if not provider or not request.query_params.get('code'):
            return Response({'detail': 'OIDC authorization failed.'}, status=400)
        try:
            metadata = _discovery(provider)
            secret_ref = provider.organization.secret_references.filter(
                name=provider.secret_ref).first() if provider.secret_ref else None
            body = {
                'grant_type': 'authorization_code', 'code': request.query_params['code'],
                'redirect_uri': flow['redirect_uri'], 'client_id': provider.client_id,
                'code_verifier': flow['verifier'],
            }
            if secret_ref:
                body['client_secret'] = resolve_secret(secret_ref)
            tokens = _json(metadata['token_endpoint'], data=urllib.parse.urlencode(body).encode(),
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
            claims = _json(metadata['userinfo_endpoint'], headers={
                'Authorization': f'Bearer {tokens["access_token"]}'})
        except Exception:
            return Response({'detail': 'OIDC token exchange failed.'}, status=502)
        subject = str(claims.get('sub') or '')
        email = str(claims.get('email') or '').lower()
        if not subject or not email or claims.get('email_verified') is False:
            return Response({'detail': 'A verified email claim is required.'}, status=403)
        domain = email.rsplit('@', 1)[-1]
        if provider.domains and domain not in {str(value).lower() for value in provider.domains}:
            return Response({'detail': 'Email domain is not allowed.'}, status=403)
        identity = ExternalIdentity.objects.filter(provider=provider, subject=subject).first()
        if identity:
            user = identity.user
        else:
            user = get_user_model().objects.filter(email__iexact=email).first()
            if user is None:
                base = (email.split('@')[0] or 'sso-user')[:120]
                username = base
                suffix = 1
                while get_user_model().objects.filter(username=username).exists():
                    suffix += 1; username = f'{base}-{suffix}'
                user = get_user_model().objects.create(username=username, email=email)
                user.set_unusable_password(); user.save(update_fields=['password'])
            identity = ExternalIdentity.objects.create(
                organization=provider.organization, provider=provider, user=user,
                subject=subject, claims=claims)
        Membership.objects.get_or_create(
            organization=provider.organization, user=user,
            defaults={'role': Membership.Role.VIEWER, 'is_active': True})
        identity.claims = claims; identity.last_login_at = timezone.now()
        identity.save(update_fields=['claims', 'last_login_at', 'updated_at'])
        refresh = RefreshToken.for_user(user)
        exchange = secrets.token_urlsafe(32)
        cache.set(f'sso-exchange:{exchange}', {
            'access': str(refresh.access_token), 'refresh': str(refresh),
            'user_id': user.id,
        }, timeout=60)
        frontend = provider.organization.settings.get('frontend_url', 'http://localhost:3000')
        return redirect(f'{frontend.rstrip("/")}/auth/sso/callback?exchange={exchange}')


class SsoExchangeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        code = str(request.data.get('exchange') or '')
        value = cache.get(f'sso-exchange:{code}')
        cache.delete(f'sso-exchange:{code}')
        if not value:
            return Response({'detail': 'Invalid or expired SSO exchange.'}, status=400)
        user = get_user_model().objects.get(id=value['user_id'])
        from apps.users.serializers import UserSerializer
        return Response({'user': UserSerializer(user).data, 'tokens': {
            'access': value['access'], 'refresh': value['refresh'],
        }}, status=status.HTTP_200_OK)
