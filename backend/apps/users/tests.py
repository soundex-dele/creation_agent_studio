"""
Tests for users app.
"""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.test import TestCase
from django.test.utils import override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from .session import refresh_cookie_name
from .licensing import generate_keypair, machine_code, sign_license

User = get_user_model()


class UserModelTest(TestCase):
    """
    Test cases for User model.
    """

    def setUp(self):
        """
        Set up test data.
        """
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

    def test_user_creation(self):
        """
        Test that a user can be created.
        """
        self.assertTrue(self.user.check_password('testpass123'))
        self.assertEqual(self.user.username, 'testuser')
        self.assertEqual(self.user.email, 'test@example.com')

    def test_user_str(self):
        """
        Test the __str__ method returns username.
        """
        self.assertTrue(str(self.user).startswith('testuser'))


class BrowserSessionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='browser-user', password='safe-test-password')
        self.client = APIClient()

    def test_refresh_token_is_only_exposed_as_httponly_cookie(self):
        login = self.client.post('/api/v1/auth/login/', {
            'username': self.user.username,
            'password': 'safe-test-password',
        }, format='json')

        self.assertEqual(login.status_code, 200)
        self.assertNotIn('refresh', login.data['tokens'])
        cookie = login.cookies[refresh_cookie_name()]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Strict')
        self.assertEqual(cookie['path'], '/api/v1/')
        first_refresh = cookie.value

        refreshed = self.client.post('/api/v1/auth/token/refresh/', {}, format='json')
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn('access', refreshed.data)
        self.assertNotIn('refresh', refreshed.data)
        self.assertNotEqual(
            refreshed.cookies[refresh_cookie_name()].value,
            first_refresh,
        )

        logged_out = self.client.post('/api/v1/auth/logout/', {}, format='json')
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(logged_out.cookies[refresh_cookie_name()]['max-age'], 0)

    def test_refresh_without_cookie_is_rejected(self):
        response = self.client.post('/api/v1/auth/token/refresh/', {}, format='json')
        self.assertEqual(response.status_code, 401)


class OfflineLicenseLoginTest(TestCase):
    def setUp(self):
        self.private_key, public_key = generate_keypair()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            LICENSE_AUTH_ENABLED=True,
            LICENSE_PRODUCT_ID='agent-studio-test',
            LICENSE_PUBLIC_KEY=public_key,
            LICENSE_FILE_PATH=str(Path(self.temp_dir.name) / 'license.lic'),
            SINGLE_TENANT_MODE=True,
            SINGLE_TENANT_ORGANIZATION_SLUG='licensed-workspace',
            SINGLE_TENANT_ORGANIZATION_NAME='Licensed Workspace',
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.temp_dir.cleanup)
        self.client = APIClient()

    def license(self, **overrides):
        now = datetime.now(timezone.utc)
        payload = {
            'version': 1,
            'license_id': 'test-license',
            'product': 'agent-studio-test',
            'machine_code': machine_code(),
            'customer': 'Test Customer',
            'edition': 'professional',
            'license_type': 'trial',
            'issued_at': (now - timedelta(minutes=1)).isoformat(),
            'expires_at': (now + timedelta(days=7)).isoformat(),
            'features': [],
        }
        payload.update(overrides)
        return sign_license(payload, self.private_key)

    def test_mode_exposes_machine_code_and_hides_registration(self):
        response = self.client.get('/api/v1/auth/mode/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['mode'], 'license')
        self.assertFalse(response.data['registration_enabled'])
        self.assertEqual(response.data['machine_code'], machine_code())

    def test_valid_license_creates_local_session_and_can_be_reused(self):
        activated = self.client.post('/api/v1/auth/license/login/', {
            'license': self.license(),
        }, format='json')

        self.assertEqual(activated.status_code, 200)
        self.assertIn('access', activated.data['tokens'])
        self.assertTrue(activated.data['user']['username'].startswith('licensed-'))
        self.assertTrue(Path(self.temp_dir.name, 'license.lic').is_file())

        reused = self.client.post('/api/v1/auth/license/login/', {}, format='json')
        self.assertEqual(reused.status_code, 200)
        self.assertEqual(reused.data['user']['id'], activated.data['user']['id'])

    def test_installed_license_is_rechecked_for_api_and_token_refresh(self):
        activated = self.client.post('/api/v1/auth/license/login/', {
            'license': self.license(),
        }, format='json')
        access = activated.data['tokens']['access']
        expired = datetime.now(timezone.utc) - timedelta(days=1)
        Path(self.temp_dir.name, 'license.lic').write_text(
            self.license(expires_at=expired.isoformat()), encoding='utf-8')

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        profile = self.client.get('/api/v1/auth/me/')
        refreshed = self.client.post('/api/v1/auth/token/refresh/', {}, format='json')

        self.assertEqual(profile.status_code, 401)
        self.assertIn('试用许可证已过期', profile.data['detail'])
        self.assertEqual(refreshed.status_code, 401)
        self.assertIn('试用许可证已过期', refreshed.data['detail'])

    def test_expired_trial_is_rejected(self):
        expired = datetime.now(timezone.utc) - timedelta(days=1)
        response = self.client.post('/api/v1/auth/license/login/', {
            'license': self.license(expires_at=expired.isoformat()),
        }, format='json')

        self.assertEqual(response.status_code, 401)
        self.assertIn('试用许可证已过期', response.data['detail'])

    def test_license_for_another_machine_is_rejected(self):
        response = self.client.post('/api/v1/auth/license/login/', {
            'license': self.license(machine_code='AS-OTHER-MACHINE'),
        }, format='json')

        self.assertEqual(response.status_code, 401)
        self.assertIn('当前电脑不匹配', response.data['detail'])

    def test_account_login_and_registration_are_disabled(self):
        login = self.client.post('/api/v1/auth/login/', {
            'username': 'someone', 'password': 'irrelevant',
        }, format='json')
        register = self.client.post('/api/v1/auth/register/', {
            'username': 'someone',
            'email': 'someone@example.com',
            'password': 'safe-test-password',
            'password_confirm': 'safe-test-password',
        }, format='json')

        self.assertEqual(login.status_code, 403)
        self.assertEqual(register.status_code, 403)
