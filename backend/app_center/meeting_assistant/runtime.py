"""Durable media adapter. All private result writes are version/lease fenced."""
from contextlib import contextmanager
from django.db import transaction
from django.utils import timezone
from modules.tenancy.database import tenant_database_context
from modules.execution.models import Run, RunLease
from core.transcription import transcribe_segments
from .backend.access import recording_for
from .backend.models import Recording, ActionItem
from .backend.storage import object_path
from .backend.analysis import analyze


@contextmanager
def current_record(payload, sink):
    with tenant_database_context(payload["organization_id"]), transaction.atomic():
        record = Recording.objects.select_for_update().filter(
            pk=payload["input"]["record_id"], organization_id=payload["organization_id"],
            active_run_id=payload["run_id"], version=payload["input"]["version"],
        ).first()
        run = Run.objects.select_for_update().filter(pk=payload["run_id"], status="running",
            organization_id=payload["organization_id"], current_attempt_id=payload["attempt_id"]).first()
        if sink.cancelled or not record or not run or not RunLease.objects.filter(
            attempt_id=payload["attempt_id"], expires_at__gt=timezone.now(), released_at__isnull=True,
        ).exists():
            raise InterruptedError("任务已取消、过期或记录已更新。")
        if run.owner_id != record.owner_id or str(run.source_id) != str(record.application_id):
            raise PermissionError("任务与录音不匹配。")
        recording_for(record.owner, record.organization_id, record.application_id, record.pk)
        yield record


def execute_meeting(payload, sink):
    def cancelled():
        if sink.cancelled:
            return True
        try:
            with current_record(payload, sink):
                return False
        except InterruptedError:
            return True

    try:
        with current_record(payload, sink) as record:
            needs_transcript = not record.segments
            record.stage = "transcribing" if needs_transcript else "analyzing"
            record.error = ""
            record.save(update_fields=["stage", "error", "updated_at"])
            path, language = object_path(record.object_key), record.language
        if needs_transcript:
            result = transcribe_segments(path, language, cancelled=cancelled,
                progress=lambda seconds: sink.emit("meeting.progress", {"stage": "transcribing", "seconds": seconds}))
            if not result["segments"]:
                raise ValueError("未识别到语音，请检查录音后重试。")
            with current_record(payload, sink) as record:
                record.segments = result["segments"]
                record.stage = "analyzing"
                record.save(update_fields=["segments", "stage", "updated_at"])
        with current_record(payload, sink) as record:
            # Resolve related tenant data before leaving the short transaction.
            _ = record.organization
        output = analyze(record, cancelled=cancelled,
            model=(payload.get("effective_config") or {}).get("model", ""),
            progress=lambda done, total: sink.emit("meeting.progress", {"stage": "analyzing", "done": done, "total": total}))
        with current_record(payload, sink) as record:
            # Old candidate rows remain available for already-confirmed links.
            # Unconfirmed rows of the same version can be safely replaced.
            record.actions.filter(analysis_version=record.version, confirmed_at__isnull=True).delete()
            confirmed = {a.title: a for a in record.actions.filter(confirmed_at__isnull=False)}
            for action in output.pop("actions"):
                prior = confirmed.get(action["title"])
                if prior and set(prior.segment_ids) & set(action["segment_ids"]):
                    prior.analysis_version = record.version
                    prior.segment_ids = action["segment_ids"]
                    prior.save(update_fields=["analysis_version", "segment_ids"])
                else:
                    ActionItem.objects.create(organization_id=record.organization_id, recording=record,
                                              analysis_version=record.version, **action)
            record.analysis = output
            record.analysis_version = record.version
            record.stage = "completed"
            record.error = ""
            record.save(update_fields=["analysis", "analysis_version", "stage", "error", "updated_at"])
        # Do not duplicate private transcript text into generic Run events.
        return {"record_id": str(record.pk), "version": record.version}
    except InterruptedError:
        raise
    except Exception as exc:
        try:
            with current_record(payload, sink) as record:
                record.error = str(exc)[:500] if isinstance(exc, ValueError) else "处理服务暂不可用，请检查模型及执行服务后重试。"
                record.stage = "failed"
                record.save(update_fields=["error", "stage", "updated_at"])
        except (InterruptedError, PermissionError):
            pass
        raise
