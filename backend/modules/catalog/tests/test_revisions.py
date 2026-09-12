import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from modules.catalog.models import Agent, AgentDraft, AgentRevision
from modules.catalog.services import canonical_content_hash, publish_agent
from modules.tenancy.models import Organization
from apps.agents.models import AgentCategory


@pytest.fixture
def catalog_owner(db):
    return get_user_model().objects.create_user(username="catalog-owner")


@pytest.fixture
def catalog_organization(catalog_owner):
    return Organization.objects.create(
        name="Catalog Organization",
        slug="catalog-organization",
        owner=catalog_owner,
    )


@pytest.fixture
def agent_with_draft(catalog_organization, catalog_owner):
    category, _ = AgentCategory.objects.get_or_create(
        slug="catalog-tests", defaults={"name": "Catalog Tests"}
    )
    agent = Agent.objects.create(
        organization=catalog_organization,
        created_by=catalog_owner,
        category=category,
        name="Writer",
        slug="writer",
        description="Writer agent",
    )
    draft = AgentDraft.objects.create(
        organization=catalog_organization,
        agent=agent,
        updated_by=catalog_owner,
        content={"model": "deepseek-chat", "system_prompt": "Write clearly."},
    )
    return agent, draft


@pytest.mark.django_db
def test_publish_creates_immutable_content_addressed_revision(agent_with_draft, catalog_owner):
    agent, draft = agent_with_draft
    revision = publish_agent(
        agent=agent,
        actor=catalog_owner,
        expected_draft_version=draft.version,
    )

    assert revision.revision_no == 1
    assert revision.content == draft.content
    assert revision.content_hash == canonical_content_hash(draft.content)
    assert revision.organization_id == agent.organization_id

    revision.content = {"system_prompt": "mutated"}
    with pytest.raises(ValidationError, match="immutable"):
        revision.save()
    with pytest.raises(ValidationError, match="immutable"):
        revision.delete()

    with pytest.raises(DatabaseError, match="immutable"):
        with transaction.atomic():
            AgentRevision.objects.filter(pk=revision.pk).update(
                content={"system_prompt": "queryset mutation"}
            )
    with pytest.raises(DatabaseError, match="immutable"):
        with transaction.atomic():
            AgentRevision.objects.filter(pk=revision.pk).delete()
    revision.refresh_from_db()
    assert revision.content == draft.content


@pytest.mark.django_db
def test_publishing_same_content_is_idempotent(agent_with_draft, catalog_owner):
    agent, draft = agent_with_draft
    first = publish_agent(
        agent=agent,
        actor=catalog_owner,
        expected_draft_version=draft.version,
    )
    second = publish_agent(
        agent=agent,
        actor=catalog_owner,
        expected_draft_version=draft.version,
    )

    assert second.id == first.id
    assert AgentRevision.objects.filter(agent=agent).count() == 1


@pytest.mark.django_db
def test_new_draft_content_creates_next_revision(agent_with_draft, catalog_owner):
    agent, draft = agent_with_draft
    first = publish_agent(
        agent=agent,
        actor=catalog_owner,
        expected_draft_version=1,
    )
    draft.content = {"model": "deepseek-chat", "system_prompt": "Write concisely."}
    draft.version = 2
    draft.save(update_fields=("content", "version", "updated_at"))

    second = publish_agent(
        agent=agent,
        actor=catalog_owner,
        expected_draft_version=2,
    )
    assert first.revision_no == 1
    assert second.revision_no == 2
    assert first.content_hash != second.content_hash


@pytest.mark.django_db
def test_publish_rejects_stale_draft_version(agent_with_draft, catalog_owner):
    agent, _draft = agent_with_draft
    with pytest.raises(ValidationError, match="Draft version changed"):
        publish_agent(
            agent=agent,
            actor=catalog_owner,
            expected_draft_version=99,
        )


@pytest.mark.django_db
def test_publish_rejects_cross_tenant_draft(agent_with_draft, catalog_owner):
    agent, draft = agent_with_draft
    other = Organization.objects.create(
        name="Other",
        slug="other-catalog-organization",
        owner=catalog_owner,
    )
    AgentDraft.objects.filter(pk=draft.pk).update(organization=other)

    with pytest.raises(ValidationError, match="same organization"):
        publish_agent(
            agent=agent,
            actor=catalog_owner,
            expected_draft_version=draft.version,
        )
