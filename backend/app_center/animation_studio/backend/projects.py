
from core.observability import log_operation
import copy
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from .models import AnimationProject, AnimationVersion
from .documents import empty_document, validate_document, asset_ids
from .access import assets_for, runs_for


def project_for(user, app, pk):
    try:
        return AnimationProject.objects.for_organization(app.organization_id).get(pk=pk, application=app, owner=user)
    except AnimationProject.DoesNotExist:
        raise NotFound("作品不存在。")


def document_assets(user, app, doc):
    ids = asset_ids(doc)
    values = assets_for(user, app, ids, multiple_audio=True)
    if any(item.archived for item in values):
        raise ValidationError("工程引用了已归档素材，请恢复素材或替换。")
    return values


@transaction.atomic
@log_operation
def save_draft(project, expected, document):
    doc = validate_document(document, previous=project.draft if project.draft.get("schema_version") == 2 else None)
    updated = AnimationProject.objects.filter(pk=project.pk, revision=expected).update(draft=doc, revision=expected + 1, updated_at=timezone.now())
    if not updated:
        return None
    project.refresh_from_db()
    return project


def legacy_document(run):
    return {"schema_version": 1, **copy.deepcopy(run.input), "source_run_id": str(run.id)}


@transaction.atomic
@log_operation
def import_history(user, app):
    """Idempotently group only chains from this owner/application/tenant."""
    runs = list(runs_for(user, app).filter(input__action="generate").order_by("created_at", "id"))
    owned = {str(run.id): run for run in runs}
    # Include deleted versions: their run links prevent resurrection and retain chain ownership.
    linked = {str(v.run_id): v.project for v in AnimationVersion.objects.for_organization(app.organization_id).filter(project__owner=user, project__application=app).select_related("project")}
    visiting = set()

    def attach(run):
        key = str(run.id)
        if key in linked:
            return linked[key]
        visiting.add(key)
        parent = str(run.input.get("source_run_id", ""))
        project = attach(owned[parent]) if parent in owned and parent not in visiting else None
        if project is None:
            project = AnimationProject.objects.create(organization_id=app.organization_id, application=app, owner=user,
                title=str(run.output_summary.get("title") or run.input.get("prompt") or "历史作品")[:200], draft=legacy_document(run))
        AnimationVersion.objects.get_or_create(run=run, defaults={"organization_id": app.organization_id, "project": project,
            "document": legacy_document(run), "note": run.input.get("prompt", "")[:1000]})
        linked[key] = project
        visiting.discard(key)
        return project

    for run in runs:
        attach(run)


def project_data(project, with_draft=True):
    result = {"id": str(project.id), "title": project.title, "archived": project.archived, "revision": project.revision,
              "updated_at": project.updated_at.isoformat()}
    if with_draft:
        result["draft"] = project.draft or empty_document()
    return result
