"""
Tests for users app.
"""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.test import TestCase
from django.test.utils import override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
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

    def test_superuser_is_created_with_application_admin_role(self):
        administrator = User.objects.create_superuser(
            username='bootstrap-admin',
            email='admin@example.com',
            password='safe-test-password',
        )

        self.assertTrue(administrator.is_superuser)
        self.assertTrue(administrator.is_staff)
        self.assertEqual(administrator.role, User.Role.ADMIN)


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

    @override_settings(REGISTRATION_ENABLED=False, LICENSE_AUTH_ENABLED=False)
    def test_private_deployment_can_disable_self_registration(self):
        mode = self.client.get('/api/v1/auth/mode/')
        register = self.client.post('/api/v1/auth/register/', {
            'username': 'uninvited-user',
            'email': 'uninvited@example.com',
            'password': 'safe-test-password',
            'password_confirm': 'safe-test-password',
        }, format='json')

        self.assertFalse(mode.data['registration_enabled'])
        self.assertEqual(register.status_code, 403)


class AdminAccountManagementTest(TestCase):
    def setUp(self):
        self.administrator = User.objects.create_user(
            username='account-admin',
            email='account-admin@example.com',
            password='safe-test-password',
            role=User.Role.ADMIN,
        )
        self.member = User.objects.create_user(
            username='ordinary-member',
            email='member@example.com',
            password='safe-test-password',
        )
        self.client = APIClient()

    @override_settings(REGISTRATION_ENABLED=False)
    def test_admin_can_create_account_while_public_registration_is_closed(self):
        self.client.force_authenticate(self.administrator)

        response = self.client.post('/api/v1/auth/admin/users/', {
            'username': 'provisioned-user',
            'email': 'provisioned@example.com',
            'role': User.Role.AUDITOR,
            'is_active': True,
            'password': 'A-safe-password-123!',
            'password_confirm': 'A-safe-password-123!',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        created = User.objects.get(username='provisioned-user')
        self.assertTrue(created.check_password('A-safe-password-123!'))
        self.assertEqual(created.role, User.Role.AUDITOR)
        self.assertNotIn('password', response.data)

    def test_non_admin_cannot_list_or_create_accounts(self):
        self.client.force_authenticate(self.member)

        listed = self.client.get('/api/v1/auth/admin/users/')
        created = self.client.post('/api/v1/auth/admin/users/', {
            'username': 'forbidden-user',
            'email': 'forbidden@example.com',
            'role': User.Role.MEMBER,
            'password': 'A-safe-password-123!',
            'password_confirm': 'A-safe-password-123!',
        }, format='json')

        self.assertEqual(listed.status_code, 403)
        self.assertEqual(created.status_code, 403)
        self.assertFalse(User.objects.filter(username='forbidden-user').exists())

    def test_password_confirmation_is_required(self):
        self.client.force_authenticate(self.administrator)

        response = self.client.post('/api/v1/auth/admin/users/', {
            'username': 'mismatch-user',
            'email': 'mismatch@example.com',
            'role': User.Role.MEMBER,
            'password': 'A-safe-password-123!',
            'password_confirm': 'another-safe-password',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('password_confirm', response.data)

    def test_admin_can_assign_platform_role(self):
        self.client.force_authenticate(self.administrator)

        response = self.client.patch(
            f'/api/v1/auth/admin/users/{self.member.id}/',
            {'role': User.Role.AUDITOR},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, User.Role.AUDITOR)
        self.assertNotIn('can_create_agents', response.data)

    def test_non_admin_cannot_assign_platform_role(self):
        self.client.force_authenticate(self.member)

        response = self.client.patch(
            f'/api/v1/auth/admin/users/{self.member.id}/',
            {'role': User.Role.AUDITOR},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, User.Role.MEMBER)

    def upload_csv(self, content):
        return self.client.post(
            '/api/v1/auth/admin/users/import/',
            {'file': SimpleUploadedFile(
                'accounts.csv', content.encode('utf-8'), content_type='text/csv')},
            format='multipart',
        )

    def test_admin_can_export_accounts_without_passwords_or_capabilities(self):
        self.client.force_authenticate(self.administrator)

        response = self.client.get('/api/v1/auth/admin/users/export/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        content = response.content.decode('utf-8-sig')
        self.assertIn('用户名,邮箱,角色,允许登录,初始密码', content)
        self.assertIn('ordinary-member,member@example.com,member,是,', content)
        self.assertNotIn('查看智能体', content)
        self.assertNotIn('safe-test-password', content)

    def test_admin_can_import_new_accounts_and_update_existing_roles(self):
        self.client.force_authenticate(self.administrator)
        response = self.upload_csv(
            '用户名,邮箱,角色,允许登录,初始密码\n'
            'ordinary-member,changed@example.com,平台审计员,是,\n'
            'imported-user,imported@example.com,member,是,A-safe-password-123!\n'
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {'total': 2, 'created': 1, 'updated': 1})
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, 'changed@example.com')
        self.assertEqual(self.member.role, User.Role.AUDITOR)
        imported = User.objects.get(username='imported-user')
        self.assertTrue(imported.check_password('A-safe-password-123!'))

    def test_last_platform_admin_cannot_be_downgraded_or_disabled(self):
        second_admin = User.objects.create_user(
            username='second-admin', role=User.Role.ADMIN,
        )
        actor = User.objects.create_superuser(username='root-operator')
        actor.role = User.Role.AUDITOR
        actor.save(update_fields=['role'])
        self.client.force_authenticate(actor)

        downgraded = self.client.patch(
            f'/api/v1/auth/admin/users/{self.administrator.id}/',
            {'role': User.Role.MEMBER}, format='json',
        )
        self.assertEqual(downgraded.status_code, 200, downgraded.data)
        disabled_last = self.client.patch(
            f'/api/v1/auth/admin/users/{second_admin.id}/',
            {'is_active': False}, format='json',
        )

        self.assertEqual(disabled_last.status_code, 400)
        second_admin.refresh_from_db()
        self.assertTrue(second_admin.is_active)

    def test_admin_cannot_change_own_platform_role_or_login_status(self):
        self.client.force_authenticate(self.administrator)

        response = self.client.patch(
            f'/api/v1/auth/admin/users/{self.administrator.id}/',
            {'role': User.Role.AUDITOR, 'is_active': False}, format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.administrator.refresh_from_db()
        self.assertEqual(self.administrator.role, User.Role.ADMIN)
        self.assertTrue(self.administrator.is_active)

    def test_csv_import_cannot_downgrade_all_platform_admins_in_one_batch(self):
        second_admin = User.objects.create_user(
            username='batch-admin', email='batch@example.com',
            role=User.Role.ADMIN,
        )
        actor = User.objects.create_superuser(username='root-import')
        actor.role = User.Role.AUDITOR
        actor.save(update_fields=['role'])
        self.client.force_authenticate(actor)
        response = self.upload_csv(
            'username,email,role,is_active,password\n'
            'account-admin,account-admin@example.com,member,true,\n'
            'batch-admin,batch@example.com,auditor,true,\n'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('平台管理员', response.data['detail'])
        self.administrator.refresh_from_db()
        second_admin.refresh_from_db()
        self.assertEqual(self.administrator.role, User.Role.ADMIN)
        self.assertEqual(second_admin.role, User.Role.ADMIN)

    def test_invalid_import_is_atomic_and_reports_row_errors(self):
        self.client.force_authenticate(self.administrator)
        response = self.upload_csv(
            'username,email,role,is_active,password\n'
            'valid-user,valid@example.com,member,true,A-safe-password-123!\n'
            'invalid-user,invalid@example.com,unknown,true,A-safe-password-123!\n'
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data['detail'], '导入校验失败，未写入任何账号。')
        self.assertEqual(response.data['errors'][0]['row'], 3)
        self.assertFalse(User.objects.filter(username='valid-user').exists())

    def test_non_admin_cannot_import_or_export_accounts(self):
        self.client.force_authenticate(self.member)

        exported = self.client.get('/api/v1/auth/admin/users/export/')
        imported = self.upload_csv(
            'username,email,role,password\n'
            'forbidden-import,forbidden@example.com,member,A-safe-password-123!\n'
        )

        self.assertEqual(exported.status_code, 403)
        self.assertEqual(imported.status_code, 403)
        self.assertFalse(User.objects.filter(username='forbidden-import').exists())


class AccountDeletionTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='delete-admin', role=User.Role.ADMIN)
        self.target = User.objects.create_user(username='delete-member', password='safe-test-password')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = f'/api/v1/auth/admin/users/{self.target.pk}/'

    def test_deletes_new_account_and_empty_personal_workspace(self):
        from apps.enterprise.models import Organization
        from .models import UserAPIKey
        workspace_id = self.target.owned_organizations.get().pk
        key, _ = UserAPIKey.issue(user=self.target)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(User.objects.filter(pk=self.target.pk).exists())
        self.assertFalse(Organization.objects.filter(pk=workspace_id).exists())
        self.assertFalse(UserAPIKey.objects.filter(pk=key.pk).exists())
        self.assertEqual(self.client.delete(self.url).status_code, 404)

    def test_rejects_anonymous_members_and_auditors(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.delete(self.url).status_code, 401)
        for role in (User.Role.MEMBER, User.Role.AUDITOR):
            self.target.role = role
            self.target.save(update_fields=['role'])
            self.client.force_authenticate(self.target)
            self.assertEqual(self.client.delete(self.url).status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())

    def test_rejects_self_system_and_unknown_accounts(self):
        system, _ = User.objects.get_or_create(username='system')
        for user, expected in ((self.admin, 400), (system, 404)):
            response = self.client.delete(f'/api/v1/auth/admin/users/{user.pk}/')
            self.assertEqual(response.status_code, expected)
            self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertEqual(self.client.delete('/api/v1/auth/admin/users/999999999/').status_code, 404)

    def test_superuser_requires_superuser_actor(self):
        self.target.is_superuser = True
        self.target.save(update_fields=['is_superuser'])
        self.assertEqual(self.client.delete(self.url).status_code, 403)
        self.admin.is_superuser = True
        self.admin.save(update_fields=['is_superuser'])
        self.assertEqual(self.client.delete(self.url).status_code, 204)

    def test_preserves_last_active_platform_admin(self):
        self.admin.is_superuser = True
        self.admin.role = User.Role.AUDITOR
        self.admin.save(update_fields=['role', 'is_superuser'])
        self.target.role = User.Role.ADMIN
        self.target.save(update_fields=['role'])
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertIn('至少保留', response.data['detail'])
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())

    def test_can_delete_another_admin_or_disabled_account(self):
        self.target.role = User.Role.ADMIN
        self.target.is_active = False
        self.target.save(update_fields=['role', 'is_active'])
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        another = User.objects.create_user(username='another-admin', role=User.Role.ADMIN)
        self.assertEqual(self.client.delete(f'/api/v1/auth/admin/users/{another.pk}/').status_code, 204)

    def test_workspace_with_content_or_other_members_is_preserved(self):
        from apps.conversations.models import Conversation
        from apps.enterprise.models import Membership, Organization
        workspace = self.target.owned_organizations.get()
        conversation = Conversation.objects.create(user=self.target, organization=workspace, title='keep')
        self.assertEqual(self.client.delete(self.url).status_code, 409)
        self.assertTrue(Conversation.objects.filter(pk=conversation.pk).exists())
        conversation.delete()
        Membership.objects.create(user=self.admin, organization=workspace)
        self.assertEqual(self.client.delete(self.url).status_code, 409)
        self.assertTrue(Organization.objects.filter(pk=workspace.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())

    def test_protected_resource_rolls_back_empty_workspace_cleanup(self):
        from apps.enterprise.models import Organization
        from apps.workflows.models import Workflow
        workspace_id = self.target.owned_organizations.get().pk
        workflow = Workflow.objects.create(
            name='keep workflow', owner=self.target,
            organization=self.admin.owned_organizations.get(),
        )
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())
        self.assertTrue(Organization.objects.filter(pk=workspace_id).exists())
        self.assertTrue(Workflow.objects.filter(pk=workflow.pk).exists())

    @override_settings(SINGLE_TENANT_MODE=True, SINGLE_TENANT_ORGANIZATION_SLUG='deletion-tenant')
    def test_single_tenant_member_deletion_preserves_shared_workspace(self):
        from apps.enterprise.models import Membership, Organization
        owner = User.objects.create_user(username='tenant-owner')
        target = User.objects.create_user(username='tenant-member')
        workspace = owner.owned_organizations.get()
        response = self.client.delete(f'/api/v1/auth/admin/users/{target.pk}/')
        self.assertEqual(response.status_code, 204, response.data)
        self.assertTrue(Organization.objects.filter(pk=workspace.pk).exists())
        self.assertFalse(Membership.objects.filter(user_id=target.pk).exists())
        self.assertEqual(self.client.delete(f'/api/v1/auth/admin/users/{owner.pk}/').status_code, 409)

    def test_deleted_account_tokens_and_keys_no_longer_authenticate(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from .models import UserAPIKey
        refresh = RefreshToken.for_user(self.target)
        access = str(refresh.access_token)
        _, raw_key = UserAPIKey.issue(user=self.target)
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        client = APIClient()
        self.assertEqual(client.get('/api/v1/auth/me/', HTTP_AUTHORIZATION=f'Bearer {access}').status_code, 401)
        self.assertEqual(client.get('/api/v1/auth/me/', HTTP_X_API_KEY=raw_key).status_code, 401)
        client.cookies[refresh_cookie_name()] = str(refresh)
        refreshed = client.post('/api/v1/auth/token/refresh/', {}, format='json')
        self.assertEqual(refreshed.status_code, 401)
        self.assertEqual(refreshed.cookies[refresh_cookie_name()]['max-age'], 0)


class ProfileAndApiKeyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='profile-user', email='before@example.com',
            password='safe-test-password',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_profile_can_be_read_and_updated(self):
        loaded = self.client.get('/api/v1/auth/me/')
        updated = self.client.patch('/api/v1/auth/me/', {
            'username': 'updated-user',
            'email': 'after@example.com',
            'avatar': 'https://example.com/avatar.png',
            'bio': '团队成员',
        }, format='json')

        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data['username'], 'updated-user')
        self.assertEqual(updated.data['email'], 'after@example.com')
        self.assertEqual(updated.data['bio'], '团队成员')

    def test_profile_cannot_change_its_own_platform_role(self):
        updated = self.client.patch('/api/v1/auth/me/', {
            'role': User.Role.ADMIN,
        }, format='json')

        self.assertEqual(updated.status_code, 200, updated.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.MEMBER)

    def test_password_change_checks_current_password(self):
        rejected = self.client.put('/api/v1/auth/me/change-password/', {
            'old_password': 'incorrect-password',
            'new_password': 'new-safe-password',
            'new_password_confirm': 'new-safe-password',
        }, format='json')
        changed = self.client.put('/api/v1/auth/me/change-password/', {
            'old_password': 'safe-test-password',
            'new_password': 'new-safe-password',
            'new_password_confirm': 'new-safe-password',
        }, format='json')

        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(changed.status_code, 200, changed.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('new-safe-password'))

    def test_api_key_is_shown_once_and_can_be_revoked(self):
        created = self.client.post('/api/v1/auth/me/generate-api-key/', {
            'name': 'Local development',
            'scopes': ['runs:read'],
        }, format='json')

        self.assertEqual(created.status_code, 201, created.data)
        self.assertTrue(created.data['api_key'].startswith('ast_'))
        listed = self.client.get('/api/v1/auth/me/api-keys/')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data), 1)
        self.assertNotIn('api_key', listed.data[0])
        self.assertEqual(listed.data[0]['scopes'], ['runs:read'])

        revoked = self.client.post(
            f"/api/v1/auth/me/api-keys/{created.data['id']}/revoke/", {})
        self.assertEqual(revoked.status_code, 204)
        self.assertIsNotNone(self.user.api_keys.get().revoked_at)


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
