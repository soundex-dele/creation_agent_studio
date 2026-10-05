from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import ContentVersion, MetricObservation, RESOURCES


def basic(record):
    result = dict(id=str(record.pk), title=record.title, status=record.status, archived=record.archived,
                  revision=record.revision, data=record.data, created_at=record.created_at.isoformat(),
                  updated_at=record.updated_at.isoformat())
    if hasattr(record, 'lead_id'):
        result['lead_id'] = str(record.lead_id)
    if hasattr(record, 'version_id'):
        result['version_id'] = str(record.version_id)
    return result


def version_data(version):
    return dict(id=str(version.pk), content_id=str(version.content_id), number=version.number,
                body=version.body, snapshot=version.snapshot, created_at=version.created_at.isoformat())


def property_gaps(prop):
    labels = dict(city='城市', district='片区', rent='租金', rental_type='出租方式', layout='户型')
    return [label for key, label in labels.items() if prop.data.get(key) in (None, '')]


def snapshot_properties(properties):
    return [basic(prop) for prop in properties]


def snapshot_changes(snapshot, property_map):
    changes = []
    for old in snapshot.get('properties', []):
        current = property_map.get(old['id'])
        if not current or current.archived or current.status != 'available':
            changes.append(f"{old['title']}：已出租、暂停推广或已归档")
        elif current.revision != old['revision']:
            changes.append(f"{old['title']}：资料已更新，请核对")
    return changes


def match_properties(lead, properties):
    req = lead.data
    output = {'matched': [], 'unknown': [], 'conflicts': []}
    for prop in properties:
        if prop.archived or prop.status != 'available':
            continue
        data = prop.data
        reasons, unknown, conflicts = [], [], []
        def check(label, actual, expected, compare):
            if expected in (None, '', []):
                return
            if actual in (None, '', 'unknown'):
                unknown.append(label + '待确认')
            elif compare(actual, expected):
                reasons.append(label + '符合')
            else:
                conflicts.append(label + '不符')
        check('最低预算', data.get('rent'), req.get('budget_min'), lambda a, b: a >= b)
        check('最高预算', data.get('rent'), req.get('budget_max'), lambda a, b: a <= b)
        check('城市', data.get('city'), req.get('city'), lambda a, b: a == b)
        check('片区', data.get('district'), req.get('districts'), lambda a, b: a in b)
        check('出租方式', data.get('rental_type'), req.get('rental_type'), lambda a, b: a == b)
        check('户型', data.get('layout'), req.get('layout'), lambda a, b: a == b)
        check('入住时间', data.get('available_from'), req.get('move_in'), lambda a, b: a <= b)
        conditions = {**data.get('conditions', {}), '电梯': data.get('elevator', 'unknown'), '可养宠': data.get('pets', 'unknown')}
        for need in req.get('must_have', []):
            check(need, conditions.get(need), 'yes', lambda a, b: a == b)
        if not any(req.get(k) not in (None, '', []) for k in ('budget_min', 'budget_max', 'city', 'districts', 'rental_type', 'layout', 'move_in', 'must_have')):
            unknown.append('客户尚未提供匹配条件')
        bucket = 'conflicts' if conflicts else 'unknown' if unknown else 'matched'
        output[bucket].append(dict(property=basic(prop), reasons=reasons, unknown=unknown, conflicts=conflicts))
    return output


def date_range(params):
    try:
        start = date.fromisoformat(params['start']) if params.get('start') else None
        end = date.fromisoformat(params['end']) if params.get('end') else None
    except (ValueError, TypeError):
        raise ValidationError('日期格式应为 YYYY-MM-DD。')
    if start and end and start > end:
        raise ValidationError('开始日期不能晚于结束日期。')
    return start, end


def in_range(value, start, end):
    return bool(value) and (not start or value[:10] >= start.isoformat()) and (not end or value[:10] <= end.isoformat())


def local_day(value, tz):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(ZoneInfo(tz)).date().isoformat()


def calendar(scope, prefs, start=None, end=None):
    today = timezone.now().astimezone(ZoneInfo(prefs['timezone'])).date().isoformat()
    properties = {str(p.pk): p for p in scope(RESOURCES['properties'])}
    events, publication_contents = [], set()
    for publication in scope(RESOURCES['publications']).select_related('version__content'):
        publication_contents.add(str(publication.version.content_id))
        if publication.archived:
            continue
        day = publication.data.get('scheduled_date')
        changes = snapshot_changes(publication.version.snapshot, properties)
        if day:
            events.append(dict(kind='publication', id=str(publication.pk), title=publication.title,
                               date=day, status=publication.status, changes=changes, record=basic(publication),
                               active=publication.status == 'planned', actionable=not changes))
    for content in scope(RESOURCES['contents']):
        if not content.archived and str(content.pk) not in publication_contents and content.data.get('planned_date'):
            blocked = [properties.get(i) for i in content.data.get('property_ids', [])]
            changes = ['关联房源不可推广'] if any(not p or p.archived or p.status != 'available' for p in blocked) else []
            events.append(dict(kind='content', id=str(content.pk), title=content.title, date=content.data['planned_date'],
                               status='draft', active=True, actionable=not changes, changes=changes, record=basic(content)))
    for kind, field, active_status in [('followups', 'due_date', 'pending'), ('viewings', 'scheduled_at', 'scheduled')]:
        for record in scope(RESOURCES[kind]).select_related('lead'):
            if record.archived:
                continue
            value = record.data.get(field)
            if not value:
                continue
            day = local_day(value, prefs['timezone']) if kind == 'viewings' else value
            events.append(dict(kind=kind, id=str(record.pk), title=record.title, date=day, status=record.status,
                               active=record.status == active_status, actionable=True, changes=[], record=basic(record),
                               lead_title=record.lead.title))
    events.sort(key=lambda e: (e['date'], e['record']['data'].get('scheduled_at', ''), e['id']))
    for event in events:
        event['overdue'] = event['active'] and event['date'] < today
    return dict(today=today, events=[e for e in events if in_range(e['date'], start, end)])


def report(scope, start=None, end=None):
    leads = [r for r in scope(RESOURCES['leads']) if in_range(r.data.get('consulted_on'), start, end)]
    viewed = {str(v.lead_id) for v in scope(RESOURCES['viewings']).filter(status='done')}
    publications = list(scope(RESOURCES['publications']).filter(status='published').select_related('version__content'))
    lead_groups = defaultdict(list)
    for lead in leads:
        lead_groups[lead.data.get('source_id') or 'unknown'].append(lead)
    def counts(items):
        total = len(items)
        visits = sum(str(lead.pk) in viewed for lead in items)
        wins = sum(bool(lead.data.get('deal_date') and lead.data.get('deal_property_id')) for lead in items)
        return dict(leads=total, viewed=visits, won=wins, viewing_rate=visits / total if total else None,
                    deal_rate=wins / total if total else None)
    rows = []
    for publication in publications:
        version = publication.version
        metadata = version.snapshot.get('content', version.content.data)
        metric = publication.metrics.first()
        rows.append(dict(id=str(publication.pk), title=publication.title, platform=metadata.get('platform'),
                         content_type=metadata.get('content_type'), persona_id=metadata.get('persona_id'),
                         property_ids=metadata.get('property_ids', []), **counts(lead_groups[str(publication.pk)]),
                         metrics=metric.data if metric else dict(views=None, likes=None, saves=None, comments=None),
                         metrics_at=metric.created_at.isoformat() if metric else None))
    known = {row['id'] for row in rows}
    unknown = [lead for lead in leads if lead.data.get('source_id') not in known]
    groups = {}
    for dimension in ['platform', 'content_type', 'persona_id', 'property_ids']:
        buckets = defaultdict(set)
        for row in rows:
            values = row[dimension] if dimension == 'property_ids' else [row[dimension]]
            for value in values or [None]:
                buckets[value or 'unknown'].update(str(lead.pk) for lead in lead_groups[row['id']])
        buckets['unknown'].update(str(lead.pk) for lead in unknown)
        groups[dimension] = [dict(key=key, **counts([lead for lead in leads if str(lead.pk) in members])) for key, members in buckets.items()]
    return dict(summary=counts(leads), publications=rows, unknown=counts(unknown), groups=groups,
                start=start.isoformat() if start else None, end=end.isoformat() if end else None,
                as_of=timezone.now().isoformat(),
                note='按首次咨询日期选取客户，截至当前统计。重复带看按客户去重；房源分组可能重叠，不可相加。平台互动数为手动记录的最近累计值，不受客户日期筛选影响。')
