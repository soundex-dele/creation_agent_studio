import hashlib
import json
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.http.request import validate_host
from rest_framework.exceptions import ValidationError

from apps.enterprise.models import QuotaPolicy
from apps.knowledge.models import KnowledgeDocument
from apps.knowledge.services import create_document
from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import CommandNotAllowed
from modules.execution.models import Run, RunCommand
from modules.execution.infrastructure.artifacts import delete_artifact_object
from apps.knowledge.index_backend import delete_document_index
from .content import editor_markdown, markdown, document_content
from .models import ResearchSource, ResearchExport


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def request_key(request):
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 160:
        raise ValidationError("请提供有效的 Idempotency-Key。")
    return key


def source_limits():
    return {"max_sources": getattr(settings, "RESEARCH_MAX_SOURCES", 20),
            "max_file_bytes": getattr(settings, "RESEARCH_MAX_FILE_BYTES", 50 * 1024 * 1024),
            "max_text_bytes": getattr(settings, "RESEARCH_MAX_TEXT_BYTES", 2 * 1024 * 1024)}


def public_origin(request):
    configured = getattr(settings, "RESEARCH_PUBLIC_URL", "").rstrip("/")
    if configured:
        parts = urlsplit(configured)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.query or parts.fragment:
            raise ValidationError("RESEARCH_PUBLIC_URL 必须是有效的前端 HTTP(S) 地址。")
        return configured
    for value in [request.headers.get("Origin", ""), request.headers.get("Referer", "")]:
        try:
            parts = urlsplit(value)
        except ValueError:
            continue
        if parts.scheme in {"http", "https"} and parts.hostname and not parts.username:
            origin = f"{parts.scheme}://{parts.netloc}"
            if origin in settings.CORS_ALLOWED_ORIGINS or validate_host(parts.hostname, settings.ALLOWED_HOSTS):
                return origin
    return request.build_absolute_uri("/").rstrip("/")


def ingest(project, user, values):
    """Caller holds the project lock. Imports are independent immutable copies."""
    limits = source_limits()
    origin = {"type": "upload"}
    mime = "application/octet-stream"
    if "file" in values:
        upload = values["file"]
        if upload.size > limits["max_file_bytes"]:
            raise ValidationError("文件超过研究资料大小上限。")
        filename, content, mime = upload.name, upload.read(limits["max_file_bytes"] + 1), upload.content_type or mime
    elif "text" in values:
        filename, content, mime = "文章.md", values["text"].encode(), "text/markdown"
        if len(content) > limits["max_text_bytes"]:
            raise ValidationError("文章超过文本大小上限。")
        origin = {"type": "text"}
    elif values["origin_type"] == "document":
        from app_center.documents.backend.access import document_for
        doc = document_for(user, project.organization_id, values["application_id"], values["origin_id"], lock=True)
        filename, content, mime = doc.title + ".md", editor_markdown(doc.content).encode(), "text/markdown"
        origin = {"type": "document", "id": str(doc.id), "application_id": doc.application_id, "version": doc.version}
    else:
        from app_center.my_drive.backend.access import application_for, space_for
        from app_center.my_drive.backend.services import entries
        from app_center.my_drive.backend.storage import object_path
        application = application_for(user, project.organization_id, values["application_id"])
        entry = get_object_or_404(entries(space_for(user, project.organization_id), application).select_for_update(),
                                 pk=values["origin_id"], kind="file", trash_batch=None, purge_pending=False)
        if entry.size > limits["max_file_bytes"]:
            raise ValidationError("文件超过研究资料大小上限。")
        try:
            with object_path(entry.object_key).open("rb") as handle:
                content = handle.read(limits["max_file_bytes"] + 1)
        except OSError:
            raise ValidationError("网盘原文件不可用。") from None
        filename, mime = entry.name, entry.media_type
        origin = {"type": "drive", "id": str(entry.id), "application_id": application.id}
    if filename.rsplit(".", 1)[-1].lower() not in {"pdf", "docx", "md", "markdown", "txt"}:
        raise ValidationError("仅支持文字 PDF、DOCX、TXT、Markdown；旧版 DOC 请转换后上传。")
    if not content or len(content) > limits["max_file_bytes"]:
        raise ValidationError("资料为空或超过文件大小上限。")
    checksum = hashlib.sha256(content).hexdigest()
    existing = project.sources.filter(document__checksum=checksum).select_related("document").first()
    if (not existing or existing.removed) and project.sources.filter(removed=False).count() >= limits["max_sources"]:
        raise ValidationError(f"每个项目最多 {limits['max_sources']} 份有效资料。")
    if existing:
        existing.removed = False
        existing.save(update_fields=["removed"])
        return existing, True
    quota, _ = QuotaPolicy.objects.get_or_create(organization=project.organization)
    stored = KnowledgeDocument.objects.filter(organization=project.organization, is_deleted=False).aggregate(n=Sum("byte_size"))["n"] or 0
    if quota.hard_limit and stored + len(content) > quota.storage_bytes_limit:
        raise ValidationError("组织资料存储容量不足。")
    document, _ = create_document(knowledge_base=project.knowledge_base, actor=user,
        title=values.get("title") or filename[:200], source_type="upload" if origin["type"] in {"upload", "drive"} else "text",
        filename=filename[:300], mime_type=mime, content=content, run_context={"research_project_id": str(project.id)})
    document.metadata = {"research_project_id": str(project.id)}
    document.save(update_fields=["metadata"])
    origin["checksum"] = checksum
    source = ResearchSource.objects.create(project=project, document=document, origin=origin)
    project.save(update_fields=["updated_at"])
    return source, False


def cancel(run, user, reason):
    if run and run.status not in {"succeeded", "failed", "cancelled", "cancelling"}:
        try:
            submit_run_command(run_id=run.id, organization_id=run.organization_id, actor=user,
                command_type=RunCommand.Type.CANCEL, idempotency_key=f"research-cancel:{run.id}", payload={"reason": reason})
        except CommandNotAllowed:
            run.refresh_from_db()
            if run.status not in {"succeeded", "failed", "cancelled"}:
                raise


def delete_project(project):
    project.deleted_at = project.deleted_at or timezone.now()
    project.cleanup_pending = True
    project.save(update_fields=["deleted_at", "cleanup_pending"])
    project.knowledge_base.is_active = False
    project.knowledge_base.save(update_fields=["is_active"])
    # Lock documents so an indexing commit cannot race the deletion marker.
    for document in project.knowledge_base.documents.select_for_update():
        document.is_deleted = True
        document.save(update_fields=["is_deleted"])
    for run in Run.objects.filter(organization=project.organization, input__research_project_id=str(project.id)):
        cancel(run, project.owner, "project_deleted")


def cleanup_project(project):
    for document in project.knowledge_base.documents.all():
        delete_document_index(document.id)
        if document.source_object_key:
            delete_artifact_object(document.source_object_key)
            document.source_object_key = ""
        document.content = ""
        document.save(update_fields=["source_object_key", "content"])
        document.chunks.all().delete()
    project.cleanup_pending = False
    project.save(update_fields=["cleanup_pending"])


@transaction.atomic
def export_result(result, user, values, key, origin):
    from .models import ResearchProject
    ResearchProject.objects.select_for_update().get(pk=result.project_id)
    request_hash = fingerprint(values)
    prior = result.exports.filter(key=key).first()
    if prior:
        if prior.request_hash != request_hash:
            raise ValidationError("同一保存请求不能用于不同目标。")
        return prior.response
    output = result.run.output_summary
    title = output["title"][:200]
    if values["target"] == "document":
        from app_center.documents.backend.access import application_for
        from app_center.documents.backend.content import validate_content, plain_text
        from app_center.documents.backend.models import Document
        application = application_for(user, result.project.organization_id, values["application_id"])
        content = validate_content(document_content(output, origin, result.project, result))
        doc = Document.objects.create(organization=result.project.organization, application=application,
                                     owner=user, title=title, content=content, plain_text=plain_text(content))
        response = {"id": str(doc.id), "application_id": application.id, "target": "document"}
    else:
        from app_center.my_drive.backend.access import application_for, space_for
        from app_center.my_drive.backend.services import create_upload, write_chunk, complete_upload
        application = application_for(user, result.project.organization_id, values["application_id"])
        space = space_for(user, result.project.organization_id)
        raw = markdown(output, origin, result.project, result).encode()
        upload = create_upload(space, application, {"name": title + ".md", "size": len(raw),
                                                   "last_modified": 0, "parent": values.get("parent")})
        for offset in range(0, len(raw), upload.chunk_size):
            chunk = raw[offset:offset + upload.chunk_size]
            write_chunk(space, application, upload.id, offset, hashlib.sha256(chunk).hexdigest(), chunk)
        upload = complete_upload(space, application, upload.id)
        response = {"id": str(upload.entry_id), "application_id": application.id, "target": "drive"}
    ResearchExport.objects.create(result=result, key=key, request_hash=request_hash, target=values["target"], response=response)
    return response
