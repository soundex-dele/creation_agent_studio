import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers as s
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from modules.platform_api.identity import Application
from modules.platform_api.conversations import Conversation
from modules.platform_api.identity import accessible_resources
from .models import Topic, Channel, Handoff, Version
from .schemas import PLATFORMS, CopyBody, Strict, text, validated
from .views import Access, Conflict, basic, version_data
from .materials import generation_context, require_confirmed, topic_materials, resolve_materials

SLUGS = ['write-image-text-copy', 'write-short-video-copy', 'wechat-viral-article', 'gzh-design', 'topic-explorer']
CHANNEL_APPS = {
    'wechat': ('wechat-viral-article', '公众号爆款写作', {'task': 'full-article'}),
    'xiaohongshu': ('write-image-text-copy', '图文文案', {'task': 'full', 'platform': 'xiaohongshu'}),
    'douyin': ('write-short-video-copy', '短视频文案', {'task': 'storyboard', 'platform': 'douyin'}),
    'moments': ('write-image-text-copy', '图文文案', {'task': 'photo-caption', 'platform': 'general'}),
}
REQUIREMENTS = '仅依据来源事实，保留已实现与未来设想的区别，不虚构效果，不加私信或销售引导。'


class ExplorationInput(Strict):
    case_ids = s.ListField(child=s.UUIDField(), min_length=1, max_length=20)
    platform = s.ChoiceField(choices=['unspecified', 'wechat', 'xiaohongshu', 'douyin', 'channels', 'moments', 'other'], allow_blank=True, required=False, default='')
    content_type = s.ChoiceField(choices=['unspecified', 'article', 'carousel', 'spoken_video', 'demo', 'caption', 'other'], allow_blank=True, required=False, default='')
    goal = s.ChoiceField(choices=['unspecified', 'help', 'attention', 'trust', 'introduction', 'conversion', 'other'], allow_blank=True, required=False, default='')
    direction = text(2000)
    audience = text(2000)
    requirements = text(30000)


def destination(view, identifier=None):
    query = accessible_resources(Application.objects.for_organization(view.kwargs['organization_id']).filter(
        is_active=True, kind='chat', slug__in=SLUGS), view.request.user, operation='run')
    return get_object_or_404(query, pk=identifier) if identifier else query


def handoff_data(row):
    slug = row.target_application.slug
    return dict(id=str(row.pk), version_id=str(row.version_id) if row.version_id else None,
        topic_id=str(row.topic_id) if row.topic_id else str(row.version.channel.topic_id) if row.version_id else None,
        source_type=row.source_type,
        platform=row.platform or (row.version.channel.platform if row.version_id else ''), target_application_id=row.target_application_id,
        kind=slug, target_id=str(row.conversation_id) if row.conversation_id else '', draft=row.draft, revision=row.revision,
        status='制作草稿已保存', created_at=row.created_at.isoformat(),
        url=f'/applications/{row.target_application_id}/chat?slug={slug}&promotionApplication={row.application_id}&promotionHandoff={row.pk}' + (f'&conversation={row.conversation_id}' if row.conversation_id else ''))


class Integrations(Access):
    def get(self, request, **kwargs):
        self.application()
        return Response([dict(id=a.pk, name=a.name, slug=a.slug) for a in destination(self)])


class Handoffs(Access):
    def get(self, request, **kwargs):
        return Response([handoff_data(row) for row in self.scope(Handoff).select_related('target_application', 'version__channel')])

    @transaction.atomic
    def post(self, request, **kwargs):
        self.lock()
        if 'case_ids' in request.data:
            return self.from_materials(request.data)
        if 'topic_id' in request.data:
            return self.from_topic(request.data)
        channel = self.linked(Channel, request.data.get('channel_id'))
        version = get_object_or_404(channel.versions, pk=s.UUIDField().run_validation(request.data.get('version_id')))
        target = destination(self, s.IntegerField().run_validation(request.data.get('target_id')))
        if target.slug == 'topic-explorer':
            raise ValidationError('选题探索请通过 case_ids 交接素材。')
        # Reopening an unchanged handoff reuses its durable form and conversation.
        old = self.scope(Handoff).filter(version=version, target_application=target).first()
        if old:
            return Response(handoff_data(old))
        source = json.dumps(dict(body=version.body, source=generation_context(version.snapshot)), ensure_ascii=False)
        if len(source) > 75000:
            raise ValidationError('所选版本资料过长，请减少素材后交接。')
        draft = dict(source=source, requirements=REQUIREMENTS)
        if target.slug == 'gzh-design':
            draft = dict(source=version.body['body'], requirements=REQUIREMENTS)
        h = Handoff.objects.create(**self.ownership(), title=channel.title, version=version, target_application=target, draft=draft)
        return Response(handoff_data(h), status=201)

    def from_materials(self, payload):
        values = validated(ExplorationInput, payload)
        materials = sorted(resolve_materials(self, values), key=lambda row: str(row.pk))
        require_confirmed(materials)
        target = destination(self).filter(slug='topic-explorer').first()
        if target is None:
            raise ValidationError('当前没有可运行的「选题探索」应用，请在应用中心安装或联系管理员开通。')
        initial = {key: value for key, value in values.items() if key != 'case_ids'}
        snapshot = dict(cases=[basic(material) for material in materials], initial=initial)
        source = json.dumps(generation_context({'cases': snapshot['cases']}), ensure_ascii=False)
        if len(source) + sum(len(value) for value in initial.values()) > 75000:
            raise ValidationError('素材与范围信息过长，请减少后交接。')
        old = self.scope(Handoff).filter(source_type='materials', target_application=target, snapshot=snapshot).first()
        if old:
            return Response(handoff_data(old))
        h = Handoff.objects.create(**self.ownership(), title='选题探索', source_type='materials',
            platform=initial['platform'], snapshot=snapshot, target_application=target,
            draft=dict(source=source, **initial))
        return Response(handoff_data(h), status=201)

    def from_topic(self, payload):
        if set(payload) - {'topic_id', 'platform'}:
            raise ValidationError('选题交接仅接受 topic_id 和 platform。')
        topic = self.linked(Topic, payload.get('topic_id'))
        if topic.archived or topic.status != 'confirmed':
            raise ValidationError('请先编辑并确认有效选题，再进入创作应用。')
        require_confirmed(topic_materials(topic))
        platform = s.ChoiceField(choices=PLATFORMS).run_validation(payload.get('platform'))
        slug, name, defaults = CHANNEL_APPS[platform]
        target = destination(self).filter(slug=slug).first()
        if target is None:
            raise ValidationError(f'当前没有可运行的「{name}」应用，请在应用中心安装或联系管理员开通。')
        snapshot = dict(cases=[basic(material) for material in topic_materials(topic)], topic=basic(topic), platform=platform)
        # Retry/reopen the same source without replacing user edits or its conversation.
        old = self.scope(Handoff).filter(topic=topic, platform=platform, target_application=target, snapshot=snapshot).first()
        if old:
            return Response(handoff_data(old))
        source = json.dumps(generation_context(snapshot), ensure_ascii=False)
        if len(source) > 75000:
            raise ValidationError('选题资料过长，请减少素材后交接。')
        requirements = REQUIREMENTS
        if platform == 'moments':
            requirements += '发布渠道为朋友圈，请生成适合朋友圈的自然配文，不制作多页图文。'
        draft = dict(source=source, requirements=requirements, **defaults)
        if topic.data.get('audience'):
            draft['audience'] = topic.data['audience']
        h = Handoff.objects.create(**self.ownership(), title=topic.title, source_type='topic', topic=topic, platform=platform,
            snapshot=snapshot, target_application=target, draft=draft)
        return Response(handoff_data(h), status=201)


class HandoffDetail(Access):
    def item(self):
        row = get_object_or_404(self.scope(Handoff).select_related('target_application', 'version__channel'), pk=self.kwargs['handoff_id'])
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
        if not row.version_id:
            raise ValidationError('请在目标应用中继续创作，无需回存。')
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
