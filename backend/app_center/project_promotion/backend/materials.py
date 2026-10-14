"""Material relationships, including the original single-case compatibility path."""
from copy import deepcopy
from rest_framework import serializers as s
from rest_framework.exceptions import ValidationError
from .models import Case, TopicMaterial


def topic_materials(topic):
    # The primary case remains authoritative for legacy topics with no join rows.
    extra = topic.materials.filter(organization_id=topic.organization_id,
        application_id=topic.application_id, owner_id=topic.owner_id).exclude(pk=topic.case_id).order_by('id')
    return [topic.case, *extra]


def resolve_materials(access, payload, fallback=None):
    if 'case_ids' in payload:
        ids = s.ListField(child=s.UUIDField(), min_length=1, max_length=20).run_validation(payload['case_ids'])
        ids = list(dict.fromkeys(str(pk) for pk in ids))
        if payload.get('case_id') and str(payload['case_id']) != ids[0]:
            raise ValidationError('case_id 必须与 case_ids 的第一份素材一致。')
    elif payload.get('case_id'):
        if fallback is not None:
            if str(payload['case_id']) != str(fallback.case_id):
                raise ValidationError('请使用 case_ids 编辑关联素材。')
            return topic_materials(fallback)
        ids = [payload['case_id']]
    elif fallback is not None:
        return topic_materials(fallback)
    else:
        raise ValidationError('请选择至少一份关联素材。')
    return [access.linked(Case, pk) for pk in ids]


def set_materials(topic, materials):
    TopicMaterial.objects.filter(topic=topic).delete()
    TopicMaterial.objects.bulk_create([TopicMaterial(organization_id=topic.organization_id,
        topic=topic, material=material) for material in materials])


def require_confirmed(materials):
    if any(m.archived or m.status != 'confirmed' for m in materials):
        raise ValidationError('请先确认所有关联素材，并恢复已归档素材。')


def snapshot_materials(snapshot):
    return snapshot.get('cases') or ([snapshot['case']] if snapshot.get('case') else [])


def generation_context(snapshot):
    # Keep the legacy alias in durable snapshots, without sending/counting it twice.
    context = deepcopy({key: value for key, value in snapshot.items() if key != 'case' or not snapshot.get('cases')})
    for row in snapshot_materials(context):
        source = row.pop('source_snapshot', None)
        if source and source.get('evidence'):
            row.get('data', {}).pop('evidence', None)
    return context


def sources_current(topic, snapshot):
    previous = {row['id']: row.get('revision') for row in snapshot_materials(snapshot)}
    current = {str(row.pk): row.revision for row in topic_materials(topic)}
    return previous == current
