import copy
import uuid
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from apps.enterprise.models import Membership
from modules.execution.models import Run
from modules.execution.infrastructure.artifacts import get_artifact_storage
from .views import BaseView
from .access import runs_for
from .models import AnimationProject, AnimationVersion, AnimationPreset, AnimationSpeechConfig, AnimationAsset
from .projects import project_for, project_data, import_history, save_draft, document_assets
from .documents import empty_document, validate_document, validate_style, builtins, FONTS


def revision(data):
    value = data.get("revision")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValidationError("请提供有效草稿修订号。")
    return value


def version_for(project, identifier):
    version = get_object_or_404(AnimationVersion.objects.select_related("run"), pk=identifier,
        organization_id=project.organization_id, project__application=project.application, project__owner=project.owner,
        deleted_at__isnull=True)
    if version.project_id != project.id and project.draft.get("source_run_id") != str(version.run_id):
        from rest_framework.exceptions import NotFound
        raise NotFound("版本不存在。")
    return version


class ProjectsView(BaseView):
    def get(self, request, **kwargs):
        app = self.application()
        import_history(request.user, app)
        items = AnimationProject.objects.for_organization(app.organization_id).filter(application=app, owner=request.user,
            archived=request.query_params.get("archived") == "1", title__icontains=request.query_params.get("q", "")[:200])
        from rest_framework.pagination import PageNumberPagination
        pagination = PageNumberPagination(); pagination.page_size = 20
        page = pagination.paginate_queryset(items, request)
        return pagination.get_paginated_response([project_data(p) for p in page])

    def post(self, request, **kwargs):
        app = self.application()
        doc = validate_document(request.data.get("draft", empty_document()))
        document_assets(request.user, app, doc)
        project = AnimationProject.objects.create(organization=app.organization, application=app, owner=request.user,
            title=str(request.data.get("title") or "未命名作品")[:200], draft=doc)
        return Response(project_data(project), status=201)


class ProjectView(BaseView):
    def get(self, request, project_id, **kwargs):
        app = self.application(); project = project_for(request.user, app, project_id)
        data = project_data(project)
        versions = list(project.versions.filter(deleted_at__isnull=True).select_related("run"))
        if not versions and not project.versions.exists() and project.draft.get("schema_version") == 1:
            versions = list(AnimationVersion.objects.filter(run_id=project.draft.get("source_run_id"), organization_id=app.organization_id,
                project__application=app, project__owner=request.user, deleted_at__isnull=True).select_related("run"))
        data["versions"] = [{"id": str(v.id), "note": v.note, "document": v.document,
            "created_at": v.created_at.isoformat(), "can_delete": v.project_id == project.id,
            "run": self.serialize(v.run, app)} for v in versions]
        data["tasks"] = [self.serialize_run(r) for r in Run.objects.for_organization(app.organization_id).filter(
            owner=request.user, source_id=str(app.id), executor_key="animation-studio", input__project_id=str(project.id)).exclude(input__action="generate").order_by("-created_at")[:20]]
        return Response(data)

    def patch(self, request, project_id, **kwargs):
        app = self.application(); p = project_for(request.user, app, project_id)
        if "title" in request.data:
            p.title = str(request.data["title"]).strip()[:200]
            if not p.title: raise ValidationError("请输入作品名称。")
        if "archived" in request.data:
            if not isinstance(request.data["archived"], bool): raise ValidationError("归档状态无效。")
            p.archived = request.data["archived"]
        p.save(update_fields=["title", "archived", "updated_at"])
        return Response(project_data(p))


class VersionView(BaseView):
    @transaction.atomic
    def delete(self, request, project_id, version_id, **kwargs):
        app = self.application()
        project = project_for(request.user, app, project_id)
        # Unlike restore, deletion must never follow a copied project's source link.
        version = get_object_or_404(AnimationVersion, pk=version_id, project=project,
            organization_id=app.organization_id)
        run = get_object_or_404(runs_for(request.user, app).select_for_update(), pk=version.run_id)
        version.refresh_from_db()
        if version.deleted_at:
            return Response(status=204)
        terminal = (Run.Status.SUCCEEDED, Run.Status.FAILED, Run.Status.CANCELLED)
        if run.status not in terminal:
            return Response({"detail": "该版本正在生成，请等待完成或取消任务后再删除。"}, status=409)
        if runs_for(request.user, app).filter(input__action="export", input__source_run_id=str(run.id)).exclude(status__in=terminal).exists():
            return Response({"detail": "该版本正在导出，请等待完成或取消导出后再删除。"}, status=409)
        version.deleted_at = timezone.now()
        version.save(update_fields=["deleted_at"])
        return Response(status=204)


class DraftView(BaseView):
    def put(self, request, project_id, **kwargs):
        app = self.application(); p = project_for(request.user, app, project_id)
        expected = revision(request.data)
        if p.revision != expected: return Response({"detail": "草稿已被更新，请选择保留本地内容或加载服务器版本。", "current": project_data(p)}, status=409)
        doc = validate_document(request.data.get("document"), previous=p.draft if p.draft.get("schema_version") == 2 else None)
        document_assets(request.user, app, doc)
        saved = save_draft(p, expected, doc)
        if not saved: return Response({"detail": "草稿保存冲突，本地内容已保留。"}, status=409)
        return Response(project_data(saved))


class ProjectActionView(BaseView):
    def post(self, request, project_id, operation, **kwargs):
        app = self.application(); p = project_for(request.user, app, project_id)
        if operation == "copy":
            cloned = AnimationProject.objects.create(organization=app.organization, application=app, owner=request.user,
                title=(p.title + " · 副本")[:200], draft=copy.deepcopy(p.draft))
            return Response(project_data(cloned), status=201)
        if operation == "restore":
            expected = revision(request.data)
            version = version_for(p, request.data.get("version_id"))
            updated = AnimationProject.objects.filter(pk=p.pk, revision=expected).update(draft=version.document, revision=expected + 1)
            if not updated: return Response({"detail": "草稿已更新，请刷新后再恢复。"}, status=409)
            p.refresh_from_db(); return Response(project_data(p))
        if operation == "convert":
            source = version_for(p, request.data.get("version_id"))
            doc = empty_document(); doc["prompt"] = source.run.input.get("prompt", ""); doc["aspect"] = source.run.input.get("aspect", "16:9")
            doc["conversion_source"] = str(source.run_id)
            cloned = AnimationProject.objects.create(organization=app.organization, application=app, owner=request.user,
                title=(p.title + " · 分镜工程")[:200], draft=doc)
            return Response(project_data(cloned), status=201)
        if operation == "apply-result":
            expected = revision(request.data)
            run = get_object_or_404(Run.objects.for_organization(app.organization_id), pk=request.data.get("run_id"),
                owner=request.user, source_id=str(app.id), executor_key="animation-studio", input__project_id=str(p.id), status="succeeded")
            artifact = get_object_or_404(run.artifacts, kind="animation-document")
            from modules.execution.infrastructure.artifacts import open_artifact
            import json
            with open_artifact(artifact) as handle: doc = validate_document(json.load(handle), complete=True)
            document_assets(request.user, app, doc)
            saved = save_draft(p, expected, doc)
            if not saved: return Response({"detail": "草稿已更新，请刷新后再应用任务结果。"}, status=409)
            return Response(project_data(saved))
        raise ValidationError("不支持的作品操作。")


class ProjectTasksView(BaseView):
    @transaction.atomic
    def post(self, request, project_id, **kwargs):
        app = self.application(); p = project_for(request.user, app, project_id)
        expected = revision(request.data)
        from modules.execution.models import IdempotencyRecord
        replay = IdempotencyRecord.objects.for_organization(app.organization_id).filter(actor=request.user,
            operation="application.run.create", key=request.headers.get("Idempotency-Key", ""), status="completed").first()
        if replay:
            run = Run.objects.for_organization(app.organization_id).filter(pk=replay.response_body.get("run_id"), owner=request.user,
                source_id=str(app.id), executor_key="animation-studio").first()
            if not run or run.input.get("project_id") != str(p.id) or run.input.get("draft_revision") != expected or any(run.input.get(k) != v for k, v in request.data.items() if k not in ("revision", "note")):
                return Response({"detail": "同一幂等键不能用于不同任务。"}, status=409)
            return Response(self.serialize(run, app) if run.input["action"] == "generate" else self.serialize_run(run))
        if p.revision != expected: return Response({"detail": "请先保存最新草稿再提交。"}, status=409)
        action = request.data.get("action")
        if action not in ("storyboard", "generate", "scene", "speech", "transcribe"):
            raise ValidationError("不支持的制作任务。")
        doc = validate_document(p.draft, complete=action not in ("storyboard", "generate"))
        document_assets(request.user, app, doc)
        values = {"action": action, "project_id": str(p.id), "draft_revision": expected, "document": doc,
                  "prompt": doc["prompt"] or p.title, "aspect": doc["aspect"], "style": doc["style"], "asset_ids": [], "duration": 30}
        for key in ("scene_id", "instruction", "voice", "speed", "asset_id"):
            if key in request.data: values[key] = request.data[key]
        from .studio_validation import validate_task
        validate_task(values)
        response = self.start(app, values)
        if response.status_code < 300 and action == "generate":
            AnimationVersion.objects.get_or_create(run_id=response.data["id"], defaults={"organization_id": app.organization_id,
                "project": p, "document": doc, "note": str(request.data.get("note") or doc.get("note") or doc["prompt"])[:1000]})
        return response


class PresetsView(BaseView):
    def get(self, request, **kwargs):
        app = self.application()
        values = [{"id": str(p.id), "name": p.name, "kind": p.kind, "data": p.data, "builtin": False} for p in
                  AnimationPreset.objects.for_organization(app.organization_id).filter(application=app, owner=request.user)]
        return Response({"results": builtins() + values, "fonts": FONTS})

    def post(self, request, **kwargs):
        app = self.application(); kind = request.data.get("kind"); data = copy.deepcopy(request.data.get("data", {}))
        if kind not in ("template", "brand") or not isinstance(data, dict): raise ValidationError("预设格式无效。")
        if kind == "template":
            data["document"] = validate_document(data.get("document"), complete=True)
            document_assets(request.user, app, data["document"])
            from .batch import validate_fields
            validate_fields(data)
        else:
            validate_style(data)
            if data.get("logo"): document_assets(request.user, app, {"brand": data})
        preset = AnimationPreset.objects.create(organization=app.organization, application=app, owner=request.user,
            name=str(request.data.get("name") or "未命名预设")[:100], kind=kind, data=data)
        return Response({"id": str(preset.id), "name": preset.name, "kind": kind, "data": data}, status=201)


class AssetView(BaseView):
    def item(self, asset_id):
        app = self.application()
        return get_object_or_404(AnimationAsset.objects.for_organization(app.organization_id), application=app, owner=self.request.user, pk=asset_id)

    def patch(self, request, asset_id, **kwargs):
        item = self.item(asset_id)
        for key in ("name", "category"):
            if key in request.data: setattr(item, key, str(request.data[key])[:100] or "素材")
        if "archived" in request.data:
            if not isinstance(request.data["archived"], bool): raise ValidationError("归档状态无效。")
            item.archived = request.data["archived"]
        item.save(update_fields=["name", "category", "archived"])
        return Response({"id": str(item.id), "name": item.name, "category": item.category, "archived": item.archived})

    def get(self, request, asset_id, **kwargs):
        item = self.item(asset_id)
        return FileResponse(get_artifact_storage().open(item.object_key), content_type=item.mime_type, filename=item.name)


class SpeechConfigView(BaseView):
    def get(self, request, **kwargs):
        app = self.application()
        config = AnimationSpeechConfig.objects.for_organization(app.organization_id).filter(application=app).first()
        return Response({"enabled": bool(config and config.enabled), "app_id": config.app_id if config else "",
            "resource_id": config.resource_id if config else "seed-tts-2.0", "secret_ref": config.secret_ref if config else "", "voices": config.voices if config else []})

    def put(self, request, **kwargs):
        app = self.application()
        if not Membership.objects.filter(organization=app.organization, user=request.user, is_active=True, role__in=[Membership.Role.OWNER, Membership.Role.ADMIN]).exists():
            raise PermissionDenied("仅组织管理员可配置配音。")
        voices = request.data.get("voices", [])
        if not isinstance(voices, list) or len(voices) > 100 or any(not isinstance(v, dict) or not v.get("id") or not v.get("name") for v in voices):
            raise ValidationError("请提供音色 ID 和名称。")
        values = {key: str(request.data.get(key, ""))[:200] for key in ("app_id", "resource_id", "secret_ref")}
        enabled = request.data.get("enabled", False)
        if not isinstance(enabled, bool): raise ValidationError("启用状态无效。")
        if enabled and (not values["resource_id"] or not values["secret_ref"] or not voices): raise ValidationError("请配置资源、密钥引用与音色。")
        if values["secret_ref"] and not app.organization.secret_references.filter(name=values["secret_ref"]).exists():
            raise ValidationError("密钥引用不存在，请先在组织设置中配置。")
        AnimationSpeechConfig.objects.update_or_create(organization=app.organization, application=app, defaults={**values, "enabled": enabled, "voices": voices})
        return self.get(request, **kwargs)
