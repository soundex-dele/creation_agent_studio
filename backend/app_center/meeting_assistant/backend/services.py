import logging
from django.db import transaction
from rest_framework.exceptions import APIException, ValidationError
from modules.execution.application.start_runs import start_application_run
from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import CommandNotAllowed
from modules.execution.models import IdempotencyRecord
from .storage import object_path

ACTIVE = {"queued", "running", "waiting_input", "waiting_children", "cancelling"}


class Conflict(APIException):
    status_code = 409
    default_detail = "记录已更新，请刷新后重试。"


def check_version(record, version):
    if type(version) is not int or version != record.version:
        raise Conflict()


def check_idle(record):
    if record.active_run and record.active_run.status in ACTIVE:
        raise Conflict("记录正在处理，请等待完成或取消后再修改。")


def start(record, user, key, operation="process"):
    if operation not in ("process", "analyze"):
        raise ValidationError({"operation": "请选择转录或分析。"})
    if operation == "analyze" and not record.segments:
        raise ValidationError("请先完成转录。")
    prior = IdempotencyRecord.objects.filter(organization_id=record.organization_id,
        actor=user, operation="application.run.create", key=key).first()
    if prior:
        # Let the platform compare the full fingerprint, including version and
        # operation, before replaying an already accepted start request.
        run, _ = start_application_run(organization_id=record.organization_id,
            application_id=record.application_id, actor=user, priority=0, idempotency_key=key,
            input_data={"record_id": str(record.pk), "version": record.version, "operation": operation})
        return run
    # The enclosing endpoint locks the record before creating the Run.
    check_idle(record)
    run, replay = start_application_run(organization_id=record.organization_id,
        application_id=record.application_id, actor=user, priority=0, idempotency_key=key,
        input_data={"record_id": str(record.pk), "version": record.version, "operation": operation})
    if not replay:
        record.active_run = run
        record.stage = "queued"
        record.error = ""
        record.save(update_fields=["active_run", "stage", "error", "updated_at"])
    return run


def cancel(record, user):
    if record.active_run and record.active_run.status in ACTIVE - {"cancelling"}:
        try:
            submit_run_command(run_id=record.active_run_id, organization_id=record.organization_id,
                actor=user, command_type="cancel", idempotency_key=f"meeting-cancel:{record.active_run_id}")
        except CommandNotAllowed:
            # The coordinator may finish after we read the record's Run.
            record.active_run.refresh_from_db()
            if record.active_run.status in ACTIVE:
                raise


def delete_audio(key):
    try:
        object_path(key).unlink(missing_ok=True)
    except OSError:
        logging.getLogger(__name__).warning("Deferred meeting audio cleanup: %s", key)


def delete_record(record, user):
    cancel(record, user)
    key = record.object_key
    record.delete()
    transaction.on_commit(lambda: delete_audio(key))


def timestamp(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02}:{seconds % 3600 // 60:02}:{seconds % 60:02}"


def evidence_text(record, refs):
    by_id = {s["id"]: s for s in record.segments}
    return "、".join(f'{timestamp(by_id[r]["start"])}–{timestamp(by_id[r]["end"])}' for r in refs if r in by_id)


def document_content(record, kind, source_url):
    nodes = []

    def paragraph(text):
        nodes.append({"type": "paragraph", "content": [{"type": "text", "text": text}]})

    def heading(text):
        nodes.append({"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": text}]})

    heading(record.title)
    paragraph(f"录音日期：{record.recorded_on} · 逐字稿版本 {record.version} · AI 整理内容请核对原文。")
    paragraph("来源录音仅所有者可访问，共享本文档不会共享录音。")
    nodes.append({"type": "paragraph", "content": [{"type": "text", "text": "查看来源录音",
        "marks": [{"type": "link", "attrs": {"href": source_url}}]}]})
    if kind == "transcript":
        for segment in record.segments:
            paragraph(f'[{timestamp(segment["start"])}–{timestamp(segment["end"])}] {segment["text"]}')
    else:
        sections = [("topics", "主题摘要"), ("decisions", "决策")]
        if kind == "materials":
            sections += [("viewpoints", "主题观点"), ("quotes", "原话引用"), ("facts", "事实素材"), ("outline", "文章提纲")]
        for section, label in sections:
            heading(label)
            values = record.analysis.get(section, [])
            if not values:
                paragraph("暂无明确内容。")
            for value in values:
                paragraph(f'{value["text"]} [{evidence_text(record, value["segment_ids"])}]')
        heading("行动项")
        for item in record.actions.filter(analysis_version=record.analysis_version):
            paragraph(f'{item.title}：{item.description} [{evidence_text(record, item.segment_ids)}]')
    return {"type": "doc", "content": nodes}
