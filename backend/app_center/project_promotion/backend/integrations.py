import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers as s
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from apps.applications.models import Application
from apps.conversations.models import Conversation
from core.resource_access import accessible_resources
from .models import Channel, Handoff, Version
from .schemas import CopyBody, validated
from .views import Access, Conflict, version_data

SLUGS = ['write-image-text-copy', 'write-short-video-copy', 'wechat-viral-article', 'gzh-design']


def destination(view, identifier=None):
    query = accessible_resources(Application.objects.for_organization(view.kwargs['organization_id']).filter(
        is_active=True, kind='chat', slug__in=SLUGS), view.request.user, operation='run')
    return get_object_or_404(query, pk=identifier) if identifier else query


def handoff_data(row):
    slug = row.target_application.slug
    return dict(id=str(row.pk), version_id=str(row.version_id), target_application_id=row.target_application_id,
        kind=slug, target_id=str(row.conversation_id) if row.conversation_id else '', draft=row.draft, revision=row.revision,
        status='制作草稿已保存', created_at=row.created_at.isoformat(),
        url=f'/applications/{row.target_application_id}/chat?slug={slug}&promotionApplication={row.application_id}&promotionHandoff={row.pk}' + (f'&conversation={row.conversation_id}' if row.conversation_id else ''),
        return_url=f'/applications/{row.application_id}/project-promotion')


class Integrations(Access):
    def get(self, request, **kwargs):
        self.application()
        return Response([dict(id=a.pk, name=a.name, slug=a.slug) for a in destination(self)])


class Handoffs(Access):
    def get(self, request, **kwargs):
        return Response([handoff_data(row) for row in self.scope(Handoff).select_related('target_application')])

    @transaction.atomic
    def post(self, request, **kwargs):
        self.lock()
        channel = self.linked(Channel, request.data.get('channel_id'))
        version = get_object_or_404(channel.versions, pk=s.UUIDField().run_validation(request.data.get('version_id')))
        target = destination(self, s.IntegerField().run_validation(request.data.get('target_id')))
        # Reopening an unchanged handoff reuses its durable form and conversation.
        old = self.scope(Handoff).filter(version=version, target_application=target).first()
        if old:
            return Response(handoff_data(old))
        source = json.dumps(dict(body=version.body, source=version.snapshot), ensure_ascii=False)
        if len(source) > 75000:
            raise ValidationError('所选版本资料过长，请减少素材后交接。')
        requirements = '仅依据来源事实，保留已实现与未来设想的区别，不虚构效果，不加私信或销售引导。'
        draft = dict(source=source, requirements=requirements)
        if target.slug == 'gzh-design':
            draft = dict(source=version.body['body'], requirements=requirements)
        h = Handoff.objects.create(**self.ownership(), title=channel.title, version=version, target_application=target, draft=draft)
        return Response(handoff_data(h), status=201)


class HandoffDetail(Access):
    def item(self):
        row = get_object_or_404(self.scope(Handoff).select_related('target_application'), pk=self.kwargs['handoff_id'])
        destination(self, row.target_application_id)
        return row

    def get(self, request, **kwargs):
        return Response(handoff_data(self.item()))

    @transaction.atomic
    def patch(self, request, **kwargs):
        self.lock()
        row = self.item()
        if request.data.get('revision') != row.revision:
            raise Conflict()
        draft = request.data.get('draft', row.draft)
        if not isinstance(draft, dict) or set(draft) - set(row.draft) or any(not isinstance(v, str) or len(v) > 80000 for v in draft.values()):
            raise ValidationError('制作草稿字段无效。')
        row.draft = {**row.draft, **draft}
        if request.data.get('conversation_id'):
            row.conversation = get_object_or_404(Conversation, pk=request.data['conversation_id'], user=request.user,
                organization_id=row.organization_id, chat_application__application_id=row.target_application_id)
        row.revision += 1
        row.save()
        return Response(handoff_data(row))


class HandoffResults(HandoffDetail):
    def get(self, request, **kwargs):
        row = self.item()
        if not row.conversation_id:
            return Response([])
        conversation = get_object_or_404(Conversation, pk=row.conversation_id, user=request.user, organization_id=row.organization_id)
        return Response([dict(id=m.pk, content=m.content, created_at=m.created_at.isoformat())
            for m in conversation.messages.filter(role='assistant', run__status='succeeded').order_by('-created_at')[:30]])

    @transaction.atomic
    def post(self, request, **kwargs):
        self.lock()
        row = self.item()
        if not row.conversation_id:
            raise ValidationError('请先在创作应用中完成生成。')
        conversation = get_object_or_404(Conversation, pk=row.conversation_id, user=request.user, organization_id=row.organization_id)
        message = get_object_or_404(conversation.messages, pk=s.IntegerField().run_validation(request.data.get('message_id')),
                                   role='assistant', run__status='succeeded')
        channel = self.linked(Channel, row.version.channel_id)
        if channel.archived:
            raise ValidationError('请先恢复渠道。')
        existing = channel.versions.filter(snapshot__handoff_id=str(row.pk), snapshot__message_id=message.pk).first()
        if existing:
            return Response(version_data(existing))
        body = dict(row.version.body)
        # Import into a new editable version; never execute or render imported HTML.
        field = 'formatted_html' if row.target_application.slug == 'gzh-design' else 'body'
        content = message.content.strip()
        if field == 'formatted_html':
            import re
            match = re.search(r'```html\s*\n(.*?)```', content, re.S | re.I)
            if match:
                content = match.group(1).strip()
            if not content.startswith('<'):
                raise ValidationError('此回复不含 HTML 正文，请在版本编辑器粘贴实际 HTML 文件内容。')
        body[field] = content
        body = validated(CopyBody, body)
        snapshot = {**row.version.snapshot, 'handoff_id': str(row.pk), 'message_id': message.pk}
        version = Version.objects.create(organization_id=channel.organization_id, channel=channel,
            number=channel.versions.count() + 1, body=body, snapshot=snapshot)
        channel.revision += 1
        channel.save(update_fields=['revision', 'updated_at'])
        return Response(version_data(version), status=201)
