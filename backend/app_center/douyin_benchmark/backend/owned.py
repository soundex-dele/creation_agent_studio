"""Account-specific, confirmed writing profiles and immutable analysis evidence."""
import copy
import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from . import models as m
from .analysis import transcript_text
from .research import scope_for
from .research_serializers import PrivateSerializer, BASE, READ
from .services import Conflict
from .views import BaseView


CONTENT_FIELDS = ('current_positioning', 'positioning', 'audience', 'content_pillars',
                  'content_boundaries', 'rules', 'examples', 'avoid', 'prompt')


def shared_materials(scope, ids):
    field = serializers.ListField(child=serializers.UUIDField(), max_length=20)
    ids = list(dict.fromkeys(str(i) for i in field.run_validation(ids)))
    rows = list(m.Inspiration.objects.filter(**scope, pk__in=ids, kind='text'))
    if len(rows) != len(ids):
        raise ValidationError('共享素材不存在、不是文本素材或不可访问。')
    return [{'id': str(r.pk), 'title': r.title, 'text': r.text} for r in rows]


class VoiceSampleSerializer(PrivateSerializer):
    usage = serializers.ChoiceField(choices=['style', 'content', 'exclude'], default='style')
    source_missing = serializers.SerializerMethodField()
    work_kind = serializers.SerializerMethodField()
    import_caption = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = m.VoiceSample
        fields = BASE + ['profile', 'work', 'source_task', 'title', 'text', 'usage', 'source_url', 'source_missing', 'work_kind', 'import_caption']
        read_only_fields = READ + ['source_url']

    def get_source_missing(self, obj):
        return bool(obj.source_url and not obj.work_id)

    def get_work_kind(self, obj):
        return obj.work.metadata.get('kind') if obj.work_id else None

    def validate(self, attrs):
        attrs = super().validate(attrs)
        import_caption = attrs.pop('import_caption', False)
        profile = attrs.get('profile', getattr(self.instance, 'profile', None))
        if self.instance and profile.pk != self.instance.profile_id:
            raise ValidationError('样本不能移到另一个档案。')
        work = attrs.get('work', getattr(self.instance, 'work', None))
        source = attrs.get('source_task', getattr(self.instance, 'source_task', None))
        if work and work.account_id != profile.account_id:
            raise ValidationError('请选择当前账号的作品。')
        if self.instance and 'work' in attrs and getattr(work, 'pk', None) != self.instance.work_id:
            raise ValidationError('样本不能更换来源作品，请新建样本。')
        if source and (not work or source.work_id != work.pk or source.kind not in ['transcribe', 'breakdown']
                       or not source.run or source.run.status != 'succeeded'):
            raise ValidationError('请选择该作品已完成的转写。')
        if import_caption:
            if not work or work.metadata.get('kind') != 'image_album':
                raise ValidationError('只能为图文作品补充发布文案。')
            if self.instance and self.instance.text.strip():
                raise ValidationError('样本已有正文，请通过编辑核对，不能覆盖已保存正文。')
            if not (work.metadata.get('description') or '').strip():
                raise ValidationError('尚未采集到图文发布文案，请刷新作品资料或手动补充。图片内文字需要另行识别。')
            attrs.update(text=work.metadata['description'], source_task=None)
        if not self.instance and work:
            attrs['source_url'] = work.metadata.get('url', '') or work.account.source_url
            if not attrs.get('text', '').strip():
                if work.metadata.get('kind') == 'image_album':
                    # This is the published caption, not OCR or an inferred body from a title.
                    attrs.update(text=work.metadata.get('description') or '', source_task=None)
                else:
                    source = m.Task.objects.filter(**self.context['scope'], work=work,
                        kind__in=['transcribe', 'breakdown'], run__status='succeeded',
                        input__media_key=work.media_key).first()
                    if source:
                        attrs.update(text=transcript_text(source.output), source_task=source)
        if len(attrs.get('text', '')) > 20000:
            raise ValidationError('样本正文超过20000字，请粘贴选定的代表性片段。')
        if not work and not attrs.get('text', getattr(self.instance, 'text', '')).strip():
            raise ValidationError('请粘贴正文或选择一条作品。')
        return attrs


class VoiceVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.VoiceVersion
        fields = ['id', 'profile', 'number', 'content', 'evidence', 'source_task', 'created_at']


def sample_snapshot(profile):
    rows = list(profile.voice_samples.exclude(usage='exclude').order_by('created_at', 'id'))
    if len(rows) > 20:
        raise ValidationError('每次最多分析20篇样本，请将其他样本标记为不学习。')
    return [{'id': str(s.pk), 'title': s.title, 'text': s.text, 'usage': s.usage,
             'work_id': str(s.work_id) if s.work_id else None,
             'source_task_id': str(s.source_task_id) if s.source_task_id else None,
             'source_url': s.source_url} for s in rows]


def freeze_analysis(scope, values, data, refs):
    account = get_object_or_404(m.Account.objects.filter(**scope, is_owned=True), pk=values.get('target_account_id'))
    profile = get_object_or_404(m.CreatorProfile.objects.filter(**scope), account=account)
    samples = sample_snapshot(profile)
    style = [s for s in samples if s['usage'] == 'style' and s['text'].strip()]
    mode = values.get('analysis_mode', 'style')
    if mode == 'style' and not style:
        raise ValidationError('文风分析至少需要一篇标记为代表风格的有效正文。可先转写，或仅分析定位。')
    if not samples:
        raise ValidationError('请先添加代表作或文案样本。')
    if len(json.dumps(samples, ensure_ascii=False)) > 120000:
        raise ValidationError('样本总量过大，请减少到12万字符以内。')
    data.update(voice_samples=samples, profile_id=str(profile.pk), target_account_id=str(account.pk),
        desired_positioning=profile.positioning, analysis_mode=mode, style_sample_count=len(style),
        account_name=account.name)
    refs.add((account.pk, None, None))


def make_prompt(content):
    return '\n\n'.join(f'【{label}】\n{content.get(key, "")}' for key, label in [
        ('positioning', '账号定位'), ('audience', '目标受众'), ('rules', '表达规则'),
        ('examples', '原文示例'), ('avoid', '避免的表达')]) + (
        '\n\n【真实素材约束】\n只使用本次明确提供的事实和经历；缺少素材时列出待补充项，不编造第一人称经历。'
        '\n保留个人特点，精简空话与重复。不推断未提供的数据，不承诺传播效果。'
        '\n\n【本次任务】\n遵循本次提供的主题、内容支柱、内容边界、时长与制作条件。')


def validate_report(value, samples, mode):
    if not isinstance(value, dict):
        raise ValueError('分析结果格式无效。')
    content = value.get('content')
    if not isinstance(content, dict) or any(not isinstance(content.get(k), str) or len(content[k]) > 20000 for k in CONTENT_FIELDS if k != 'prompt'):
        raise ValueError('定位与文风字段不完整。')
    evidence = value.get('findings')
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 40:
        raise ValueError('分析必须包含有依据的结论。')
    sources = {s['id']: s for s in samples}
    for row in evidence:
        if not isinstance(row, dict) or row.get('category') not in ['positioning', 'keep', 'improve']:
            raise ValueError('结论类型无效。')
        source = sources.get(row.get('sample_id'))
        quote = row.get('quote')
        if not source or not isinstance(quote, str) or not quote.strip() or len(quote) > 2000:
            raise ValueError('结论缺少有效样本引用。')
        available = source['text'] or source['title']
        if quote not in available or not isinstance(row.get('text'), str) or not 0 < len(row['text']) <= 4000:
            raise ValueError('引用原文不存在或结论内容无效。')
        if row['category'] != 'positioning' and (mode != 'style' or source['usage'] != 'style' or not source['text'].strip()):
            raise ValueError('文风结论只能引用代表风格的正文。')
    content = {k: content[k] for k in CONTENT_FIELDS if k != 'prompt'}
    if mode != 'style':
        content.update(rules='', examples='', avoid='')
    content['prompt'] = make_prompt(content)
    return {'content': content, 'findings': evidence}


def analyze_voice(task, config, sink, save):
    from .research_runtime import structured
    data = task.input
    save('分析账号定位' if data['analysis_mode'] == 'positioning' else '分析账号定位与文风')
    prompt = ('分析我自己的账号，区分历史定位、目标定位、受众推测和建议。只从正文提取文风，'
        'content用途只参考内容，不学习风格。保持个人特点，改善空话与重复；'
        '建议覆盖开头、句式、用词、节奏、观点、案例、结尾。'
        '返回 {"content":{"current_positioning":"历史定位（标题分析注明初步推测）",'
        '"positioning":"建议目标定位","audience":"目标受众（推测）","content_pillars":"内容支柱",'
        '"content_boundaries":"内容边界","rules":"建议保留及改善的表达规则",'
        '"examples":"带样本名称的原文示例","avoid":"避免的表达"},'
        '"findings":[{"category":"positioning|keep|improve","text":"结论",'
        '"sample_id":"实际样本ID","quote":"样本原文的连续摘录"}]}。'
        '仅定位模式时rules、examples、avoid返回空字符串。不编造经历或数据。')
    result = structured(task, prompt, {'samples': data['voice_samples'], 'mode': data['analysis_mode'],
        'desired_positioning': data['desired_positioning']}, config,
        lambda value: validate_report(value, data['voice_samples'], data['analysis_mode']), sink)
    save('completed', {**result, 'voice_evidence': data['voice_samples'], 'profile_id': data['profile_id'],
        'target_account_id': data['target_account_id'], 'sample_count': len(data['voice_samples']),
        'warning': '初步分析：代表风格的有效正文不足三篇。' if data['style_sample_count'] < 3 else ''})


class VoiceVersionsView(BaseView):
    def profile(self, lock=False):
        scope = scope_for(self.app(), self.request.user)
        qs = m.CreatorProfile.objects.filter(**scope)
        return get_object_or_404(qs.select_for_update() if lock else qs, pk=self.kwargs['profile_id']), scope

    def get(self, request, **kwargs):
        profile, _ = self.profile()
        return Response(VoiceVersionSerializer(profile.voice_versions.order_by('-number'), many=True).data)

    @transaction.atomic
    def post(self, request, **kwargs):
        # Same lock order as record writes and research submissions.
        type(request.user).objects.select_for_update().get(pk=request.user.pk)
        profile, scope = self.profile(True)
        if request.data.get('revision') != profile.revision:
            raise Conflict('档案已更新，请刷新后重试。')
        if kwargs.get('version_id'):
            version = get_object_or_404(profile.voice_versions, pk=kwargs['version_id'])
        else:
            content = request.data.get('content')
            if not isinstance(content, dict) or any(not isinstance(content.get(k), str) or len(content[k]) > 20000 for k in CONTENT_FIELDS):
                raise ValidationError('请填写完整定位、文风和提示词，每项不超过20000字。')
            if not content['positioning'].strip() or not content['prompt'].strip():
                raise ValidationError('定位和提示词不能为空。')
            source = None
            evidence = sample_snapshot(profile)
            if request.data.get('source_task_id'):
                source_id = serializers.UUIDField().run_validation(request.data['source_task_id'])
                source = get_object_or_404(m.Task.objects.filter(**scope, kind='voice_analysis',
                    run__status='succeeded', input__profile_id=str(profile.pk)), pk=source_id)
                evidence = source.input['voice_samples']
            saved = {k: content[k] for k in CONTENT_FIELDS}
            saved['shared_inspiration_ids'] = [r['id'] for r in shared_materials(scope, profile.shared_inspiration_ids)]
            saved.update(conditions=profile.conditions, experiences=profile.experiences, products=profile.products)
            latest = profile.voice_versions.order_by('-number').first()
            version = m.VoiceVersion.objects.create(**scope, profile=profile, number=latest.number + 1 if latest else 1,
                content=saved, evidence=evidence, source_task=source)
        profile.active_version = version
        for key in ['positioning', 'audience', 'content_pillars', 'content_boundaries']:
            setattr(profile, key, version.content[key])
        profile.voice = version.content['rules']
        profile.revision += 1
        profile.save()
        return Response({'version': VoiceVersionSerializer(version).data, 'revision': profile.revision})


def owned_brief(scope, values, refs):
    account = get_object_or_404(m.Account.objects.filter(**scope, is_owned=True), pk=values['target_account_id'])
    profile = get_object_or_404(m.CreatorProfile.objects.filter(**scope).select_related('active_version'), account=account)
    if values.get('profile_id') and str(values['profile_id']) != str(profile.pk):
        raise ValidationError('创作档案与目标账号不匹配。')
    version = profile.active_version
    if not version or version.profile_id != profile.pk:
        raise ValidationError('请先确认并启用该账号的定位与文风版本。')
    content = copy.deepcopy(version.content)
    materials = shared_materials(scope, content.get('shared_inspiration_ids', []))
    refs.add((account.pk, None, None))
    return {'positioning': content['positioning'], 'audience': content['audience'],
        'conditions': content.get('conditions', ''), 'theme': values.get('theme') or '依据账号定位推荐下一条内容',
        'target_account_id': str(account.pk), 'account_name': account.name,
        'voice_version_id': str(version.pk), 'voice_version_number': version.number,
        'voice_profile': content, 'voice_evidence': copy.deepcopy(version.evidence), 'shared_materials': materials,
        'history': [{'id': str(w.pk), 'title': w.metadata.get('title', ''), 'description': w.metadata.get('description', '')}
                    for w in account.works.order_by('-updated_at')[:100]],
        'history_note': '重复提醒仅覆盖已采集的最近100条作品。'}


def validate_owned_topics(value):
    from .analysis import validate_topics
    basic = validate_topics(value)
    for clean, raw in zip(basic['topics'], value['topics']):
        for key in ['pillar', 'reason', 'materials_needed', 'duplicate_note']:
            if not isinstance(raw.get(key), str) or not 0 < len(raw[key]) <= 3000:
                raise ValueError('账号选题必须说明内容支柱、适配原因、所需素材和重复情况。')
            clean[key] = raw[key]
    return basic
