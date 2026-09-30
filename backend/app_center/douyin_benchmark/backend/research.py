"""Private cross-account research, immutable evidence and numeric observations."""
import hashlib
import json
from collections import deque
from datetime import timedelta
from statistics import median
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from modules.execution.application.start_runs import start_application_run
from . import models as m
from .provider import work_web_url, ordered_media_urls
from .scoring import rank
from .services import Conflict

METRICS = ('likes', 'comments', 'collects', 'shares')


def scope_for(app, user):
    return {'organization_id': app.organization_id, 'application_id': app.pk, 'owner_id': user.pk}


def task_scope(task):
    return {k: getattr(task, k) for k in ['organization_id', 'application_id', 'owner_id']}


def works_for(scope):
    return m.Work.objects.filter(**{f'account__{k}': v for k, v in scope.items()}).select_related('account')


def work_data(work):
    return {**work.metadata, 'id': str(work.pk), 'account_id': str(work.account_id), 'account_name': work.account.name,
            'is_owned': work.account.is_owned, 'url': work_web_url(work.metadata), 'captured_at': work.updated_at.isoformat(),
            'video_url': next(iter(ordered_media_urls(work.media_urls)), ''), 'has_upload': bool(work.media_key)}


def valid_date(value):
    try:
        date = parse_datetime(value or '')
        return date if date and timezone.is_aware(date) else None
    except (ValueError, TypeError):
        return None


def selected_accounts(scope, ids, group=''):
    qs = m.Account.objects.filter(**scope)
    if ids:
        qs = qs.filter(pk__in=ids)
        if qs.count() != len(set(ids)):
            raise ValidationError('所选账号不存在或不可访问。')
    if group:
        qs = qs.filter(group=group)
    return list(qs.order_by('id')[:50])


def sample(scope, account_ids, days, now=None):
    """Round robin latest batch rows; each observation keeps its actual timestamp."""
    now = now or timezone.now()
    queues, total, coverage = [], 0, []
    for account in selected_accounts(scope, account_ids):
        batch = account.tasks.filter(kind='collect', snapshots__isnull=False).distinct().first()
        rows = []
        if batch:
            for snap in batch.snapshots.select_related('work__account').order_by('id'):
                date = valid_date(snap.data.get('published_at'))
                if date and now - timedelta(days=days) <= date <= now:
                    row = {**snap.data, 'id': str(snap.work_id), 'account_id': str(account.pk), 'account_name': account.name,
                           'captured_at': snap.captured_at.isoformat(), 'url': work_web_url(snap.data)}
                    rows.append(row)
        rows.sort(key=lambda row: row['published_at'], reverse=True)
        coverage.append({'account_id': str(account.pk), 'account_name': account.name, 'available': len(rows), 'sampled': 0})
        total += len(rows)
        queues.append(deque(rows))
    result = []
    while len(result) < 200 and any(queues):
        for index, queue in enumerate(queues):
            if queue and len(result) < 200:
                result.append(queue.popleft())
                coverage[index]['sampled'] += 1
    return result, {'available': total, 'sampled': len(result), 'accounts': coverage, 'days': days, 'as_of': now.isoformat()}


def comparison(scope, ids, days):
    from ..runtime import account_statistics
    accounts = selected_accounts(scope, ids)
    result = []
    for account in accounts:
        rows, coverage = sample(scope, [account.pk], days)
        captured = max((valid_date(r['captured_at']) for r in rows), default=timezone.now())
        ranked = rank(rows, captured)
        medians = {key: median(values) if (values := [r[key] for r in rows if type(r.get(key)) is int]) else None for key in METRICS}
        result.append({'account_id': str(account.pk), 'name': account.name, 'captured_at': captured.isoformat() if rows else None,
                       **account_statistics(rows), 'medians': medians, 'eligible_sample': ranked['sample_size'],
                       'outstanding_share': (sum(r['outstanding'] for r in ranked['items']) / ranked['sample_size']) if ranked['sample_size'] and ranked['median_likes'] and ranked['sample_size'] >= 10 else None,
                       'explanation': ranked['explanation'], 'coverage': coverage})
    return {'days': days, 'accounts': result, 'note': '仅比较已采集样本；采集时间与作品年龄可能不同。'}


def record_observation(task, work, data, captured_at):
    point, created = m.MetricObservation.objects.get_or_create(task=task, work=work,
        defaults={'captured_at': captured_at, 'data': {key: data.get(key) for key in METRICS}})
    return point, created


def trend(work):
    # Old snapshots remain readable before the resumable backfill is run.
    points = {str(s.batch_id): {'captured_at': s.captured_at, 'data': s.data} for s in work.snapshot_set.all()}
    for point in work.observations.all():
        points[str(point.task_id)] = {'captured_at': point.captured_at, 'data': point.data}
    output, previous = [], None
    for point in sorted(points.values(), key=lambda row: row['captured_at']):
        values = {k: point['data'].get(k) for k in METRICS}
        hours = (point['captured_at'] - previous['captured_at']).total_seconds() / 3600 if previous else None
        delta = {k: values[k] - previous['data'][k] if previous and type(values[k]) is int and type(previous['data'].get(k)) is int else None for k in METRICS}
        output.append({'captured_at': point['captured_at'].isoformat(), 'values': values, 'delta': delta,
                       'per_hour': {k: round(v / hours, 3) if v is not None and hours and hours > 0 else None for k, v in delta.items()}})
        previous = point
    return output


def publication_summary(scope):
    """Descriptive grouping only: no causal ranking or estimated private metrics."""
    groups = {'by_theme': {}, 'by_expression': {}}
    now = timezone.now()
    for publication in m.Publication.objects.filter(**scope).select_related('work'):
        for dimension, label in [('by_theme', publication.theme or '未分类'), ('by_expression', (publication.title + ' / ' + publication.hook).strip(' /') or '未记录表达')]:
            rows = groups[dimension].setdefault(label, [])
            rows.append(publication.work.metadata)
    output = {}
    for dimension, buckets in groups.items():
        output[dimension] = []
        for label, rows in buckets.items():
            ages = [(now - date).total_seconds() / 86400 for row in rows if (date := valid_date(row.get('published_at'))) and date <= now]
            output[dimension].append({'label': label, 'sample_count': len(rows),
                'medians': {key: median(values) if (values := [r[key] for r in rows if type(r.get(key)) is int]) else None for key in METRICS},
                'age_days': [round(min(ages), 1), round(max(ages), 1)] if ages else None})
    return {**output, 'note': '按当前已关联作品的最新采集值分组；作品年龄、采集时间及样本量不同，不用于证明表达方案的因果效果。'}


def freeze(scope, values):
    data = json.loads(json.dumps(values, default=str))
    kind = values['kind']
    accounts = selected_accounts(scope, values['account_ids'], values.get('group', ''))
    data['account_ids'] = sorted(str(a.pk) for a in accounts)
    works = list(works_for(scope).filter(pk__in=values['work_ids']))
    if len(works) != len(values['work_ids']):
        raise ValidationError('所选作品不存在或不可访问。')
    if kind == 'joint' and any(w.metadata.get('kind') != 'video' for w in works):
        raise ValidationError('联合拆解只支持视频。')
    refs = {(a.pk, None, None) for a in accounts} if kind in ['radar', 'compare'] else set()
    refs.update((w.account_id, w.pk, None) for w in works)
    data['evidence'] = [work_data(w) for w in works]
    if kind in ['radar', 'compare']:
        if not accounts:
            raise ValidationError('当前范围没有可研究账号。')
        data['evidence'], data['coverage'] = sample(scope, data['account_ids'], values['days'])
        if not data['evidence']:
            raise ValidationError('当前范围暂无已采集作品，请先采集或扩大时间范围。')
        if kind == 'compare':
            data['comparison'] = comparison(scope, data['account_ids'], values['days'])
        else:
            for row in data['evidence']:
                media_key = m.Work.objects.get(pk=row['id']).media_key
                source = m.Task.objects.filter(**scope, work_id=row['id'], kind__in=['transcribe', 'breakdown'], run__status='succeeded', input__media_key=media_key).first()
                row['basis'] = 'transcript' if source and source.output.get('segments') else 'title_description'
                if row['basis'] == 'transcript':
                    row['transcript'] = ' '.join(s.get('text', '') for s in source.output['segments'])[:4000]
            signature = hashlib.sha256(json.dumps([data['account_ids'], values['days'], values.get('group', '')]).encode()).hexdigest()
            data['scope_key'] = signature
            prior = m.Task.objects.filter(**scope, kind='radar', input__scope_key=signature, run__status='succeeded').first()
            data['previous_topics'] = [t['title'] for t in prior.output.get('topics', [])] if prior else None
    source = None
    if values.get('source_task_id'):
        source = get_object_or_404(m.Task.objects.filter(**scope, run__status='succeeded'), pk=values['source_task_id'])
        refs.update((link.account_id, link.work_id, source.pk) for link in source.source_links.all())
        if source.account_id:
            refs.add((source.account_id, source.work_id, source.pk))
        data['reference'] = {k: v for k, v in source.output.items() if k != 'frames'}
        if kind == 'needs':
            if source.kind != 'comments':
                raise ValidationError('请选择评论采集任务。')
            batch = get_object_or_404(m.CommentBatch, task=source)
            data['comments'] = [{'id': f'comment:{c.pk}', 'text': c.text, 'parent_id': c.parent_id, 'platform_id': c.platform_id, 'likes': c.likes} for c in batch.comments.all()[:500]]
            if not data['comments']:
                raise ValidationError('该批次暂无可分析评论。')
    if values.get('source_version_id'):
        version = get_object_or_404(m.ScriptVersion.objects.filter(**{f'task__{k}': v for k, v in scope.items()}, task__kind__in=['script', 'rewrite']), pk=values['source_version_id'])
        data['content'] = version.content
        source = version.task
        if source.account_id:
            refs.add((source.account_id, source.work_id, source.pk))
        refs.update((link.account_id, link.work_id, source.pk) for link in source.source_links.all())
    if kind == 'review':
        pubs = m.Publication.objects.filter(**scope).select_related('work__account')
        if values['work_ids']:
            pubs = pubs.filter(work_id__in=values['work_ids'])
        data['publications'] = [{'id': str(p.pk), 'work': work_data(p.work), 'theme': p.theme, 'title': p.title, 'hook': p.hook,
                                 'trend': trend(p.work)[-30:]} for p in pubs[:100]]
        refs.update((p.work.account_id, p.work_id, None) for p in pubs[:100])
        if not data['publications']:
            raise ValidationError('请先关联自己的发布作品。')
    if kind in ['topics', 'script']:
        if kind == 'script':
            if not source or source.kind != 'topics':
                raise ValidationError('请选择已完成的选题任务。')
            data.update(brief=source.input['brief'], reference=source.input.get('reference', {}), topic=source.output['topics'][values['topic_index']])
        else:
            profile = get_object_or_404(m.CreatorProfile.objects.filter(**scope), pk=values['profile_id']) if values.get('profile_id') else m.CreatorProfile.objects.filter(**scope, is_default=True).first()
            brief = {key: getattr(profile, key, '') if profile else '' for key in ['positioning', 'audience', 'conditions']}
            if profile:
                brief['profile'] = {key: getattr(profile, key) for key in ['name', 'positioning', 'audience', 'experiences', 'products', 'voice', 'conditions']}
            brief.update({k: data[k] for k in ['positioning', 'audience', 'theme', 'conditions', 'duration', 'production_format'] if k in data})
            if values.get('idea_id'):
                idea = get_object_or_404(m.Idea.objects.filter(**scope), pk=values['idea_id'])
                brief.setdefault('theme', idea.title)
                data['reference'] = {**data.get('reference', {}), 'idea': {'title': idea.title, 'notes': idea.notes}}
            if values.get('brand_profile_id'):
                from app_center.brand_library.backend.views import private_profiles
                brand = get_object_or_404(private_profiles(scope['organization_id'], m.CreatorProfile._meta.get_field('owner').remote_field.model.objects.get(pk=scope['owner_id'])), pk=values['brand_profile_id'])
                brief['brand'] = {'name': brand.name, 'positioning': brand.positioning, 'voice': brand.voice}
            if not brief.get('theme', '').strip() or not brief.get('positioning', '').strip():
                raise ValidationError('请填写定位与主题，或选择创作档案和选题。')
            data['brief'] = brief
            data.setdefault('reference', {})
    return data, refs


@transaction.atomic
def start_research(app, user, values, key):
    if not key or len(key) > 160:
        raise ValidationError('请提供不超过160字符的Idempotency-Key。')
    # Serialize the user's mutations, including first creation without a row to lock.
    type(user).objects.select_for_update().get(pk=user.pk)
    scope = scope_for(app, user)
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
    prior = m.Task.objects.filter(**scope, account=None, request_key=key).first()
    if prior:
        if prior.request_hash != fingerprint:
            raise Conflict('同一请求键不能用于不同参数。')
        return prior
    data, refs = freeze(scope, values)
    task = m.Task.objects.create(**scope, kind=values['kind'], request_key=key, request_hash=fingerprint, input=data)
    m.TaskSource.objects.bulk_create([m.TaskSource(task=task, account_id=a, work_id=w, source_task_id=s) for a, w, s in refs])
    task.run, _ = start_application_run(organization_id=app.organization_id, application_id=app.pk, actor=user,
        input_data={'task_id': str(task.pk)}, priority=0, idempotency_key=f'dy:{task.pk}')
    task.save(update_fields=['run'])
    return task
