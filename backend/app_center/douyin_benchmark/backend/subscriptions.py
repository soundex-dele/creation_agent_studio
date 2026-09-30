"""Private subscriptions serviced by the existing automation scheduler process."""
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from modules.tenancy.database import tenant_database_context
from . import models as m
from .research import task_scope
from .services import start, ACTIVE

logger = logging.getLogger(__name__)
DEFAULT_RULES = {'percent': 50, 'likes': 100, 'comments': 20, 'collects': 20}
BLOCKING = {'auth', 'credentials', 'challenge', 'risk_control', 'not_configured', 'signature'}


def notice(scope, key, title, kind, body, account=None, work=None):
    return m.Notification.objects.get_or_create(**scope, dedup_key=key, defaults={
        'title': title[:300], 'kind': kind, 'body': body, 'account': account, 'work': work})


def growth_notice(task, work, point):
    subscription = m.Subscription.objects.filter(account=work.account).first()
    if not subscription:
        return
    previous = work.observations.filter(captured_at__lt=point.captured_at).order_by('-captured_at', '-id').first()
    if not previous:
        return
    rules = {**DEFAULT_RULES, **subscription.rules}
    changes = {}
    for key in ['likes', 'comments', 'collects']:
        before, after = previous.data.get(key), point.data.get(key)
        if type(before) is not int or type(after) is not int:
            continue
        delta = after - before
        if delta > 0 and delta >= rules[key] and (before == 0 or delta / before * 100 >= rules['percent']):
            changes[key] = {'before': before, 'after': after, 'delta': delta}
    if changes:
        notice(task_scope(task), f'growth:{work.pk}:{task.pk}', '作品互动明显增长', 'growth',
               {'changes': changes, 'from': previous.captured_at.isoformat(), 'to': point.captured_at.isoformat()}, work.account, work)


def collection_failure(task, code, message):
    if not task.input.get('subscription_id'):
        return
    if code in BLOCKING:
        subscription = m.Subscription.objects.filter(pk=task.input['subscription_id'], **task_scope(task)).first()
        if subscription:
            subscription.enabled, subscription.next_run_at, subscription.blocked_reason = False, None, message[:500]
            subscription.revision += 1
            subscription.save()
    notice(task_scope(task), f'collection-error:{task.pk}', '订阅采集需要处理' if code in BLOCKING else '本次订阅采集未完整完成',
           'error', {'message': message[:500], 'task_id': str(task.pk)}, task.account)


def dispatch_due(now=None):
    from apps.enterprise.models import Organization
    from .access import application_for
    now = now or timezone.now()
    for org_id in Organization.objects.filter(is_active=True).values_list('pk', flat=True).iterator():
        with tenant_database_context(org_id):
            ids = list(m.Subscription.objects.filter(organization_id=org_id, enabled=True, next_run_at__lte=now).values_list('pk', flat=True)[:500])
            for pk in ids:
                try:
                    with transaction.atomic():
                        # Common owner lock also serializes two schedulers across different accounts.
                        row = m.Subscription.objects.select_related('owner').filter(pk=pk).first()
                        if not row:
                            continue
                        type(row.owner).objects.select_for_update().get(pk=row.owner_id)
                        row = m.Subscription.objects.select_for_update().select_related('account', 'owner').filter(pk=pk, enabled=True, next_run_at__lte=now).first()
                        if not row:
                            continue
                        scope = task_scope(row)
                        try:
                            application_for(row.owner, org_id, row.application_id)
                            if not m.CollectorConfig.objects.filter(**scope).exists():
                                raise ValueError('采集配置已清除。')
                        except Exception as exc:
                            from rest_framework.exceptions import APIException
                            from django.http import Http404
                            if not isinstance(exc, (APIException, Http404, ValueError)):
                                raise
                            row.enabled, row.next_run_at, row.blocked_reason = False, None, '采集配置或应用访问权限已失效，请修复后恢复。'
                            row.revision += 1
                            row.save()
                            notice(scope, f'blocked:{row.pk}:{row.revision}', '订阅已暂停', 'error', {'message': row.blocked_reason}, row.account)
                            continue
                        due = row.next_run_at
                        steps = int((now - due).total_seconds() // (row.interval_hours * 3600))
                        scheduled = due + timedelta(hours=steps * row.interval_hours)
                        # Keep a due subscription pending while another account of this user runs.
                        if m.Task.objects.filter(organization_id=org_id, owner_id=row.owner_id, run__status__in=ACTIVE, input__subscription_id__isnull=False).exists():
                            continue
                        row.next_run_at = scheduled + timedelta(hours=row.interval_hours)
                        row.save(update_fields=['next_run_at', 'updated_at'])
                        account = m.Account.objects.select_for_update().get(pk=row.account_id)
                        if account.tasks.filter(kind='collect', run__status__in=ACTIVE).exists():
                            continue
                        start(account, {'kind': 'collect', 'count': row.count, 'subscription_id': str(row.pk),
                            'tracked_work_ids': [str(w.pk) for w in row.tracked_works.all()]}, f'sub:{row.pk}:{scheduled.isoformat()}')
                except Exception:
                    logger.exception('Douyin subscription dispatch failed id=%s', pk)
            make_digests(org_id, now)


def make_digests(org_id, now):
    local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    if local.hour < 9:
        return
    end = local.replace(hour=9, minute=0, second=0, microsecond=0)
    cutoff = end - timedelta(days=1)
    scopes = m.Subscription.objects.filter(organization_id=org_id).values('organization_id', 'application_id', 'owner_id').distinct()
    for scope in scopes:
        if m.Digest.objects.filter(**scope, day=local.date()).exists():
            continue
        points = m.MetricObservation.objects.filter(**{f'task__{k}': v for k, v in scope.items()}, captured_at__gte=cutoff, captured_at__lt=end).select_related('work').order_by('captured_at')
        notifications = m.Notification.objects.filter(**scope, created_at__gte=cutoff, created_at__lt=end).exclude(kind='digest')
        changes = {}
        for point in points:
            previous = point.work.observations.filter(captured_at__lt=point.captured_at).order_by('-captured_at').first()
            if previous:
                for key in ['likes', 'comments', 'collects']:
                    a, b = previous.data.get(key), point.data.get(key)
                    if type(a) is int and type(b) is int and b != a:
                        row = changes.setdefault(str(point.work_id), {'work_id': str(point.work_id), 'title': point.work.metadata.get('title', ''), 'delta': {}})
                        row['delta'][key] = row['delta'].get(key, 0) + b - a
        if not changes and not notifications.exists():
            continue
        with transaction.atomic():
            body = {'from': cutoff.isoformat(), 'to': end.isoformat(), 'changes': list(changes.values()),
                'new_works': notifications.filter(kind='new_work').count(), 'growth_alerts': notifications.filter(kind='growth').count(), 'errors': notifications.filter(kind='error').count()}
            digest, _ = m.Digest.objects.get_or_create(**scope, day=local.date(), defaults={'body': body})
            notice(scope, f'digest:{local.date()}', f'{local.date()} 研究日报', 'digest', {'digest_id': str(digest.pk), **body})
