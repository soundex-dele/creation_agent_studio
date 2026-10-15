from apps.applications.models import Application, ApplicationAccessGrant
from apps.enterprise.models import Membership
from .test_douyin import ctx  # noqa: F401


def target(ctx, organization=None, **extra):
    return Application.objects.create(
        organization=organization or ctx.org, category=ctx.app.category,
        slug="animation-studio", name="动画制作", kind="custom",
        created_by=ctx.owner, visibility="organization", **extra,
    )


def test_destinations_only_include_active_same_organization_applications(ctx):
    animation = target(ctx)
    target(ctx, organization=ctx.reader.owned_organizations.get())
    response = ctx.client.get(ctx.root + "/animation-integrations")
    assert response.status_code == 200
    assert response.data == [{"id": animation.pk, "name": "动画制作"}]
    animation.is_active = False
    animation.save(update_fields=["is_active"])
    assert ctx.client.get(ctx.root + "/animation-integrations").data == []


def test_discovery_permission_is_not_enough_to_import(ctx):
    animation = target(ctx)
    animation.visibility = "restricted"
    animation.save(update_fields=["visibility"])
    Membership.objects.filter(organization=ctx.org, user=ctx.reader).update(role=Membership.Role.VIEWER)
    grant = ApplicationAccessGrant.objects.create(application=animation, user=ctx.reader, role="viewer")
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(ctx.root + "/animation-integrations").data == []
    grant.role = "user"
    grant.save(update_fields=["role"])
    assert ctx.client.get(ctx.root + "/animation-integrations").data == [{"id": animation.pk, "name": "动画制作"}]


def test_source_application_access_is_required(ctx):
    target(ctx)
    ctx.app.is_active = False
    ctx.app.save(update_fields=["is_active"])
    assert ctx.client.get(ctx.root + "/animation-integrations").status_code == 404
