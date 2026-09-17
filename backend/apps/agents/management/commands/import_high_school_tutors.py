"""Import the optional high-school subject tutor agents."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.agents.high_school_tutors import (
    TUTOR_DEFINITION_BY_SUBJECT,
    TUTOR_DEFINITIONS,
)
from apps.agents.models import Agent, AgentCategory
from apps.enterprise.models import Organization
from modules.catalog.models import AgentDeployment, AgentDraft
from modules.catalog.services import publish_agent, switch_agent_deployment


CATEGORY = {
    "slug": "high-school-education",
    "name": "高中课程辅导",
    "description": "面向高一至高三的学科答疑、方法指导与复习辅导",
    "icon": "🎓",
    "order": 8,
}


class Command(BaseCommand):
    help = "按需导入并发布高中九大学科辅导智能体（不会由系统自动执行）。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization",
            help="目标组织的 slug 或 UUID；只有一个启用组织时可以省略。",
        )
        parser.add_argument(
            "--subjects",
            nargs="+",
            choices=tuple(TUTOR_DEFINITION_BY_SUBJECT),
            metavar="SUBJECT",
            help=(
                "仅导入指定学科，可多选。可选值："
                + ", ".join(TUTOR_DEFINITION_BY_SUBJECT)
                + "。默认导入全部。"
            ),
        )

    def handle(self, *args, **options):
        organization = self._resolve_organization(options.get("organization"))
        requested = options.get("subjects")
        definitions = (
            [TUTOR_DEFINITION_BY_SUBJECT[subject] for subject in requested]
            if requested
            else list(TUTOR_DEFINITIONS)
        )

        self.stdout.write(
            f"[高中课程辅导] 目标组织：{organization.name} ({organization.slug})"
        )
        created_count = 0
        updated_count = 0

        with transaction.atomic():
            category = self._upsert_category()
            for definition in definitions:
                created = self._import_tutor(
                    organization=organization,
                    category=category,
                    definition=definition,
                )
                created_count += int(created)
                updated_count += int(not created)
                action = "新建" if created else "同步"
                self.stdout.write(
                    f"  [{action}] {definition.name} ({definition.subject})"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"[完成] 共处理 {len(definitions)} 个智能体："
                f"新建 {created_count}，同步 {updated_count}；均已发布并部署。"
            )
        )

    def _resolve_organization(self, identifier):
        queryset = Organization.objects.filter(is_active=True)
        if identifier:
            organization = queryset.filter(slug=identifier).first()
            if organization is None:
                try:
                    organization = queryset.filter(pk=identifier).first()
                except (TypeError, ValueError):
                    organization = None
            if organization is None:
                raise CommandError(f"找不到启用的组织：{identifier}")
            return organization

        organizations = list(queryset.order_by("created_at")[:2])
        if not organizations:
            raise CommandError("数据库中没有启用的组织，无法导入智能体。")
        if len(organizations) > 1:
            raise CommandError(
                "数据库中存在多个启用组织，请使用 --organization 指定 slug 或 UUID。"
            )
        return organizations[0]

    @staticmethod
    def _upsert_category():
        category, _ = AgentCategory.objects.update_or_create(
            slug=CATEGORY["slug"],
            defaults={key: value for key, value in CATEGORY.items() if key != "slug"},
        )
        return category

    @staticmethod
    def _import_tutor(*, organization, category, definition):
        metadata = {
            "name": definition.name,
            "description": definition.description,
            "icon": definition.icon,
            "category": category,
            "created_by": organization.owner,
            "is_public": True,
            "is_active": True,
        }
        agent, created = Agent.objects.update_or_create(
            organization=organization,
            slug=definition.slug,
            defaults=metadata,
        )
        content = {
            "version": "1.0.0",
            "system_prompt": definition.system_prompt,
            "model_config": {},
            "tool_config": [],
            "knowledge_config": [],
            "guardrail_config": {},
            "workflow_config": {},
            "skill_bindings": [],
        }

        draft = AgentDraft.objects.filter(agent=agent).first()
        if draft is None:
            draft = AgentDraft.objects.create(
                organization=organization,
                agent=agent,
                updated_by=organization.owner,
                content=content,
            )
        elif draft.content != content:
            draft.content = content
            draft.version += 1
            draft.updated_by = organization.owner
            draft.save(
                update_fields=("content", "version", "updated_by", "updated_at")
            )

        revision = publish_agent(
            agent=agent,
            actor=organization.owner,
            expected_draft_version=draft.version,
            release_notes=f"{definition.name}初始课程辅导策略 v1.0.0",
        )
        deployment = AgentDeployment.objects.filter(agent=agent).first()
        if deployment is None or deployment.revision_id != revision.id:
            switch_agent_deployment(
                agent=agent,
                actor=organization.owner,
                revision_id=revision.id,
                expected_version=deployment.version if deployment else 0,
            )
        return created
