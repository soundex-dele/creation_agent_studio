from django.test import TestCase
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentCategory
from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership, Organization
from apps.users.models import User


class ResourcePermissionApiTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="permission-admin",
            password="secret",
            role=User.Role.ADMIN,
        )
        self.member = User.objects.create_user(
            username="permission-member",
            password="secret",
        )
        self.other_member = User.objects.create_user(
            username="permission-other",
            password="secret",
        )
        self.organization = Organization.objects.create(
            name="Permission Organization",
            slug="permission-organization",
            owner=self.admin,
        )
        Membership.objects.create(
            organization=self.organization,
            user=self.admin,
            role=Membership.Role.OWNER,
        )
        Membership.objects.create(
            organization=self.organization,
            user=self.member,
            role=Membership.Role.VIEWER,
        )
        agent_category = AgentCategory.objects.create(
            name="Permission Agents",
            slug="permission-agents",
        )
        application_category = ApplicationCategory.objects.create(
            name="Permission Applications",
            slug="permission-applications",
        )
        self.agent = Agent.objects.create(
            category=agent_category,
            name="Permission Agent",
            slug="permission-agent",
            description="Hidden by default",
            created_by=self.member,
            organization=self.organization,
        )
        self.application = Application.objects.create(
            category=application_category,
            name="Permission Application",
            slug="permission-application",
            description="Hidden by default",
            created_by=self.member,
            organization=self.organization,
        )

    @staticmethod
    def client_for(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_new_resources_are_admin_only_and_hidden_from_regular_users(self):
        self.assertEqual(self.agent.access_scope, Agent.AccessScope.ADMIN)
        self.assertEqual(
            self.application.access_scope,
            Application.AccessScope.ADMIN,
        )

        member_client = self.client_for(self.member)
        self.assertEqual(
            member_client.get(f"/api/v1/agents/{self.agent.id}/").status_code,
            404,
        )
        self.assertEqual(
            member_client.get(
                f"/api/v1/apps/{self.application.slug}/"
            ).status_code,
            404,
        )

        admin_client = self.client_for(self.admin)
        self.assertEqual(
            admin_client.get(f"/api/v1/agents/{self.agent.id}/").status_code,
            200,
        )
        self.assertEqual(
            admin_client.get(
                f"/api/v1/apps/{self.application.slug}/"
            ).status_code,
            200,
        )

    def test_only_admin_can_update_restricted_access(self):
        member_client = self.client_for(self.member)
        denied = member_client.put(
            f"/api/v1/agents/{self.agent.id}/permissions/",
            {
                "access_scope": "restricted",
                "allowed_user_ids": [self.member.id],
            },
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

        admin_client = self.client_for(self.admin)
        updated = admin_client.put(
            f"/api/v1/agents/{self.agent.id}/permissions/",
            {
                "access_scope": "restricted",
                "allowed_user_ids": [self.member.id],
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["allowed_user_ids"], [self.member.id])
        self.assertEqual(
            member_client.get(f"/api/v1/agents/{self.agent.id}/").status_code,
            200,
        )
        self.assertEqual(
            self.client_for(self.other_member).get(
                f"/api/v1/agents/{self.agent.id}/"
            ).status_code,
            404,
        )

    def test_account_view_capability_or_explicit_selection_grants_access(self):
        member_client = self.client_for(self.member)
        other_client = self.client_for(self.other_member)

        self.assertEqual(
            member_client.get(f"/api/v1/agents/{self.agent.id}/").status_code,
            404,
        )
        self.member.can_view_agents = True
        self.member.save(update_fields=["can_view_agents"])
        self.assertEqual(
            member_client.get(f"/api/v1/agents/{self.agent.id}/").status_code,
            200,
        )

        self.assertEqual(
            other_client.get(f"/api/v1/agents/{self.agent.id}/").status_code,
            404,
        )
        self.other_member.can_view_agents = True
        self.other_member.save(update_fields=["can_view_agents"])
        self.assertEqual(
            other_client.get(f"/api/v1/agents/{self.agent.id}/").status_code,
            404,
        )
        self.other_member.can_view_agents = False
        self.other_member.save(update_fields=["can_view_agents"])
        Membership.objects.create(
            organization=self.organization,
            user=self.other_member,
            role=Membership.Role.VIEWER,
        )
        self.client_for(self.admin).put(
            f"/api/v1/agents/{self.agent.id}/permissions/",
            {
                "access_scope": "restricted",
                "allowed_user_ids": [self.other_member.id],
            },
            format="json",
        )
        self.assertEqual(
            other_client.get(f"/api/v1/agents/{self.agent.id}/").status_code,
            200,
        )

    def test_application_view_capability_grants_access_without_selection(self):
        member_client = self.client_for(self.member)

        self.assertEqual(
            member_client.get(
                f"/api/v1/apps/{self.application.slug}/"
            ).status_code,
            404,
        )
        self.member.can_view_applications = True
        self.member.save(update_fields=["can_view_applications"])
        self.assertEqual(
            member_client.get(
                f"/api/v1/apps/{self.application.slug}/"
            ).status_code,
            200,
        )

    def test_organization_scope_and_catalog_detail_use_same_access_rule(self):
        admin_client = self.client_for(self.admin)
        updated = admin_client.put(
            f"/api/v1/apps/{self.application.slug}/permissions/",
            {"access_scope": "organization", "allowed_user_ids": []},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.data)

        member_client = self.client_for(self.member)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.id)}
        self.assertEqual(
            member_client.get(
                f"/api/v1/apps/{self.application.slug}/",
                **headers,
            ).status_code,
            200,
        )
        self.assertEqual(
            member_client.get(
                f"/api/v1/organizations/{self.organization.id}/applications/"
                f"{self.application.id}",
                **headers,
            ).status_code,
            200,
        )

        self.application.access_scope = Application.AccessScope.ADMIN
        self.application.save(update_fields=["access_scope"])
        self.assertEqual(
            member_client.get(
                f"/api/v1/organizations/{self.organization.id}/applications/"
                f"{self.application.id}",
                **headers,
            ).status_code,
            404,
        )

    def test_admin_can_delegate_agent_create_and_update_separately(self):
        member_client = self.client_for(self.member)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.id)}
        payload = {
            "category": self.agent.category_id,
            "name": "Delegated Agent",
            "slug": "delegated-agent",
            "description": "Created through delegated access",
            "system_prompt": "Help the user.",
        }

        self.assertEqual(
            member_client.post(
                "/api/v1/agents/", payload, format="json", **headers
            ).status_code,
            403,
        )
        self.member.can_create_agents = True
        self.member.save(update_fields=["can_create_agents"])
        created = member_client.post(
            "/api/v1/agents/", payload, format="json", **headers
        )
        self.assertEqual(created.status_code, 201, created.data)

        update_url = f"/api/v1/agents/{created.data['id']}/"
        self.assertEqual(
            member_client.patch(
                update_url,
                {"description": "Not allowed yet", "system_prompt": "Help."},
                format="json",
                **headers,
            ).status_code,
            403,
        )
        self.member.can_view_agents = True
        self.member.can_update_agents = True
        self.member.save(update_fields=["can_view_agents", "can_update_agents"])
        updated = member_client.patch(
            update_url,
            {"description": "Delegated update", "system_prompt": "Help."},
            format="json",
            **headers,
        )
        self.assertEqual(updated.status_code, 200, updated.data)

    def test_admin_can_delegate_agent_delete_separately(self):
        member_client = self.client_for(self.member)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.id)}
        delete_url = f"/api/v1/agents/{self.agent.id}/"

        self.assertEqual(member_client.delete(delete_url, **headers).status_code, 403)
        self.member.can_view_agents = True
        self.member.can_delete_agents = True
        self.member.save(update_fields=["can_view_agents", "can_delete_agents"])

        deleted = member_client.delete(delete_url, **headers)
        self.assertEqual(deleted.status_code, 204, deleted.data)
        self.assertFalse(Agent.objects.filter(pk=self.agent.pk).exists())

    def test_admin_can_delegate_agent_toggle_separately(self):
        member_client = self.client_for(self.member)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.id)}
        status_url = f"/api/v1/agents/{self.agent.id}/status/"

        self.assertEqual(
            member_client.patch(
                status_url, {"is_active": False}, format="json", **headers
            ).status_code,
            403,
        )
        self.member.can_view_agents = True
        self.member.can_toggle_agents = True
        self.member.save(update_fields=["can_view_agents", "can_toggle_agents"])

        disabled = member_client.patch(
            status_url, {"is_active": False}, format="json", **headers
        )
        self.assertEqual(disabled.status_code, 200, disabled.data)
        self.assertFalse(disabled.data["is_active"])
        enabled = member_client.patch(
            status_url, {"is_active": True}, format="json", **headers
        )
        self.assertEqual(enabled.status_code, 200, enabled.data)
        self.assertTrue(enabled.data["is_active"])

    def test_application_creation_and_update_remain_admin_only(self):
        member_client = self.client_for(self.member)
        base_url = f"/api/v1/organizations/{self.organization.id}/applications"
        payload = {
            "category_id": self.application.category_id,
            "name": "Delegated Application",
            "slug": "delegated-application",
            "description": "Created through delegated access",
            "content": {
                "executor_kind": "media",
                "executor_key": "delegated-media",
            },
        }

        self.assertEqual(
            member_client.post(base_url, payload, format="json").status_code,
            403,
        )
        self.member.can_view_applications = True
        self.member.can_toggle_applications = True
        self.member.save(update_fields=[
            "can_view_applications", "can_toggle_applications",
        ])
        self.assertEqual(
            member_client.post(base_url, payload, format="json").status_code,
            403,
        )
        draft_url = f"{base_url}/{self.application.id}/draft"
        self.assertEqual(
            member_client.put(
                draft_url,
                {"expected_version": 1, "content": payload["content"]},
                format="json",
            ).status_code,
            403,
        )

    def test_admin_can_delegate_application_toggle_only(self):
        member_client = self.client_for(self.member)
        status_url = (
            f"/api/v1/organizations/{self.organization.id}/applications/"
            f"{self.application.id}"
        )

        self.assertEqual(
            member_client.patch(
                status_url, {"is_active": False}, format="json"
            ).status_code,
            403,
        )
        self.member.can_toggle_applications = True
        self.member.save(update_fields=["can_toggle_applications"])
        selected = self.client_for(self.admin).put(
            f"/api/v1/apps/{self.application.slug}/permissions/",
            {
                "access_scope": "restricted",
                "allowed_user_ids": [self.member.id],
            },
            format="json",
        )
        self.assertEqual(selected.status_code, 200, selected.data)
        disabled = member_client.patch(
            status_url, {"is_active": False}, format="json"
        )
        self.assertEqual(disabled.status_code, 200, disabled.data)
        self.assertFalse(disabled.data["is_active"])
