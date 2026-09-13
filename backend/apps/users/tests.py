"""
Tests for users app.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from .session import refresh_cookie_name

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
