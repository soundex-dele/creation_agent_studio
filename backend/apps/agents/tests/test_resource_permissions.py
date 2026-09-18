from django.test import TestCase
from rest_framework.test import APIClient

from apps.agents.models import Agent, AgentAccessGrant, AgentCategory
from apps.applications.models import (
    Application,
    ApplicationAccessGrant,
    ApplicationCategory,
)
from apps.enterprise.models import Membership, Organization
from apps.users.models import User
from core.resource_access import (
    can_access_resource,
    can_manage_resource_permissions,
    can_toggle_applications,
    can_update_applications,
)


class ResourcePermissionApiTest(TestCase):
    def setUp(self):
        self.platform_admin = User.objects.create_user(
            username="platform-admin", role=User.Role.ADMIN,
        )
        self.owner = User.objects.create_user(username="organization-owner")
        self.creator = User.objects.create_user(username="resource-creator")
        self.viewer = User.objects.create_user(username="resource-viewer")
        self.org_admin = User.objects.create_user(username="organization-admin")
        self.outsider = User.objects.create_user(username="other-organization-user")
        self.organization = Organization.objects.create(
            name="Permission Organization",
            slug="permission-organization",
            owner=self.owner,
        )
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.creator, Membership.Role.VIEWER),
            (self.viewer, Membership.Role.VIEWER),
            (self.org_admin, Membership.Role.ADMIN),
        ):
            Membership.objects.create(
                organization=self.organization, user=user, role=role,
            )
        self.other_organization = Organization.objects.create(
            name="Other Organization",
            slug="other-permission-organization",
            owner=self.outsider,
        )
        Membership.objects.create(
            organization=self.other_organization,
            user=self.outsider,
            role=Membership.Role.OWNER,
        )
        agent_category = AgentCategory.objects.create(
            name="Permission Agents", slug="permission-agents",
        )
        application_category = ApplicationCategory.objects.create(
            name="Permission Applications", slug="permission-applications",
        )
        self.agent = Agent.objects.create(
            category=agent_category,
            name="Permission Agent",
            slug="permission-agent",
            description="Private by default",
            created_by=self.creator,
            organization=self.organization,
        )
        self.application = Application.objects.create(
            category=application_category,
            name="Permission Application",
            slug="permission-application",
            description="Private by default",
            created_by=self.creator,
            organization=self.organization,
        )

    @staticmethod
    def client_for(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_private_resource_is_visible_to_creator_and_administrators_only(self):
        self.assertEqual(self.agent.visibility, Agent.Visibility.PRIVATE)
        detail = f"/api/v1/agents/{self.agent.id}/"

        self.assertEqual(self.client_for(self.creator).get(detail).status_code, 200)
        self.assertEqual(self.client_for(self.org_admin).get(detail).status_code, 200)
        self.assertEqual(self.client_for(self.platform_admin).get(detail).status_code, 200)
        self.assertEqual(self.client_for(self.viewer).get(detail).status_code, 404)
        self.assertEqual(self.client_for(self.outsider).get(detail).status_code, 404)

    def test_creator_can_manage_permissions_despite_viewer_membership(self):
        response = self.client_for(self.creator).put(
            f"/api/v1/agents/{self.agent.id}/permissions/",
            {
                "visibility": "restricted",
                "grants": [{"user_id": self.viewer.id, "role": "user"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["visibility"], "restricted")
        self.assertEqual(
            response.data["grants"],
            [{"user_id": self.viewer.id, "role": "user"}],
        )
        self.assertTrue(can_manage_resource_permissions(self.agent, self.creator))

    def test_restricted_grant_roles_form_an_operation_ladder(self):
        self.agent.visibility = Agent.Visibility.RESTRICTED
        self.agent.save(update_fields=["visibility"])
        grant = AgentAccessGrant.objects.create(
            agent=self.agent, user=self.viewer, role=AgentAccessGrant.Role.VIEWER,
        )

        self.assertTrue(can_access_resource(self.agent, self.viewer, operation="discover"))
        self.assertFalse(can_access_resource(self.agent, self.viewer, operation="run"))
        grant.role = AgentAccessGrant.Role.USER
        grant.save(update_fields=["role"])
        self.assertTrue(can_access_resource(self.agent, self.viewer, operation="run"))
        self.assertFalse(can_access_resource(self.agent, self.viewer, operation="operate"))
        grant.role = AgentAccessGrant.Role.OPERATOR
        grant.save(update_fields=["role"])
        self.assertTrue(can_access_resource(self.agent, self.viewer, operation="operate"))
        self.assertFalse(can_access_resource(self.agent, self.viewer, operation="edit"))
        grant.role = AgentAccessGrant.Role.EDITOR
        grant.save(update_fields=["role"])
        self.assertTrue(can_access_resource(self.agent, self.viewer, operation="edit"))

    def test_grants_are_limited_to_active_members_of_resource_organization(self):
        url = f"/api/v1/agents/{self.agent.id}/permissions/"
        invalid = self.client_for(self.creator).put(url, {
            "visibility": "restricted",
            "grants": [{"user_id": self.outsider.id, "role": "user"}],
        }, format="json")
        duplicate_creator = self.client_for(self.creator).put(url, {
            "visibility": "restricted",
            "grants": [{"user_id": self.creator.id, "role": "editor"}],
        }, format="json")

        self.assertEqual(invalid.status_code, 400)
        self.assertIn("grants", invalid.data)
        self.assertEqual(duplicate_creator.status_code, 400)
        self.assertFalse(self.agent.access_grants.exists())

    def test_permission_response_only_offers_members_of_the_resource_organization(self):
        response = self.client_for(self.org_admin).get(
            f"/api/v1/agents/{self.agent.id}/permissions/"
        )

        self.assertEqual(response.status_code, 200, response.data)
        available_ids = {item["id"] for item in response.data["available_users"]}
        self.assertIn(self.viewer.id, available_ids)
        self.assertIn(self.org_admin.id, available_ids)
        self.assertNotIn(self.creator.id, available_ids)
        self.assertNotIn(self.outsider.id, available_ids)

    def test_organization_visibility_uses_membership_role_without_cross_tenant_leak(self):
        self.agent.visibility = Agent.Visibility.ORGANIZATION
        self.agent.save(update_fields=["visibility"])

        self.assertTrue(can_access_resource(self.agent, self.viewer, operation="run"))
        self.assertFalse(can_access_resource(self.agent, self.viewer, operation="operate"))
        self.assertTrue(can_access_resource(self.agent, self.org_admin, operation="edit"))
        self.assertFalse(can_access_resource(self.agent, self.outsider, operation="discover"))

    def test_application_grants_and_organization_roles_use_the_same_model(self):
        self.application.visibility = Application.Visibility.RESTRICTED
        self.application.save(update_fields=["visibility"])
        grant = ApplicationAccessGrant.objects.create(
            application=self.application,
            user=self.viewer,
            role=ApplicationAccessGrant.Role.OPERATOR,
        )

        self.assertTrue(can_toggle_applications(self.viewer, self.application))
        self.assertFalse(can_update_applications(self.viewer, self.application))
        grant.role = ApplicationAccessGrant.Role.EDITOR
        grant.save(update_fields=["role"])
        self.assertTrue(can_update_applications(self.viewer, self.application))
        self.assertTrue(can_update_applications(self.org_admin, self.application))
        self.assertTrue(can_update_applications(self.platform_admin, self.application))

    def test_non_manager_cannot_change_permissions(self):
        self.application.visibility = Application.Visibility.ORGANIZATION
        self.application.save(update_fields=["visibility"])
        response = self.client_for(self.viewer).put(
            f"/api/v1/apps/{self.application.slug}/permissions/",
            {"visibility": "organization", "grants": []},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
