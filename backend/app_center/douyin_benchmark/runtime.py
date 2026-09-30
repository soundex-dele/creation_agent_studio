"""Private durable jobs: input snapshots and all writes fenced by the active lease."""

from core.observability import log_operation
from contextlib import contextmanager
from datetime import datetime
import logging
import traceback
import time
from django.db import OperationalError, connection, transaction
from django.utils import timezone
from modules.tenancy.database import tenant_database_context
from modules.execution.models import Run, RunLease
from modules.execution.runtime.child import _SuspendExecution
from .backend.transcription import transcribe_segments
from .backend.creation_formats import DEFAULT_FORMAT, format_instruction
from .backend.models import Task, Work, Snapshot, ScriptVersion
from .backend.access import account_for, application_for
from .backend.provider import CollectionError
from .backend.collector_config import LocalDTKClient as DTKClient
from .backend.scoring import rank
from .backend import media, analysis


@contextmanager
def current(payload, sink):
    with tenant_database_context(payload["organization_id"]), transaction.atomic():
        task = Task.objects.select_for_update().select_related("account", "owner", "organization", "application", "run").filter(
            pk=payload["input"]["task_id"], run_id=payload["run_id"], organization_id=payload["organization_id"]).first()
        run = Run.objects.select_for_update().filter(pk=payload["run_id"], status="running", current_attempt_id=payload["attempt_id"]).first()
        if sink.cancelled or not task or not run or not RunLease.objects.filter(attempt_id=payload["attempt_id"],
                released_at__isnull=True, expires_at__gt=timezone.now()).exists():
            raise InterruptedError("任务已取消或执行租约已失效。")
        if run.owner_id != task.owner_id or str(run.source_id) != str(task.application_id):
            raise PermissionError("任务不匹配。")
        application_for(task.owner, payload["organization_id"], task.application_id)
        if task.account_id:
            account_for(task.owner, payload["organization_id"], task.application_id, task.account_id)
        if task.source_links.exclude(account__organization_id=task.organization_id, account__application_id=task.application_id, account__owner_id=task.owner_id).exists():
            raise PermissionError('来源归属已变更。')
        yield task


def save_task_progress(payload, sink, stage, output=None, error="", progress=None):
    # A coordinator event/heartbeat can write between our SQLite read and update.
    # Retry the entire fenced transaction with a fresh snapshot, never the media/LLM work.
    for attempt in range(6):
        try:
            with current(payload, sink) as active:
                active.stage, active.error = stage, error
                if output is not None:
                    active.output = output
                if progress is not None:
                    active.progress = progress
                active.save(update_fields=["stage", "error", "output", "progress"])
            break
        except OperationalError as exc:
            busy = connection.vendor == "sqlite" and any(word in str(exc).lower() for word in ("locked", "busy"))
            if not busy:
                raise
            if attempt == 5:
                raise ValueError("保存任务进度时数据库繁忙，请稍后重试。") from None
            time.sleep(.02 * (2 ** attempt))
    sink.emit("progress.updated", {"stage": stage, **(progress or {})})


@log_operation
def execute(payload, sink):
    last_stage = "准备任务"
    def check():
        with current(payload, sink):
            pass

    def save(stage, output=None, error="", progress=None):
        nonlocal last_stage
        last_stage = stage
        save_task_progress(payload, sink, stage, output, error, progress)

    try:
        with current(payload, sink) as task:
            data, kind = task.input, task.kind
        config = payload.get("effective_config") or (payload.get("definition_snapshot") or {}).get("effective_config") or {}
        if kind == "collect":
            client = DTKClient(account=task.account, check=check)
            save("采集账号资料")
            profile = client.profile(data["source_url"])
            with current(payload, sink) as active:
                active.account.platform_id = profile["platform_id"]
                active.account.name = profile["name"]
                active.account.profile = profile
                active.account.save()
            captured = timezone.now()
            had_samples = task.account.works.exists()
            complete, reason = False, ""
            try:
                for items, complete in client.pages(profile["platform_id"], data["count"]):
                    with current(payload, sink) as active:
                        for item in items:
                            work, created = Work.objects.update_or_create(account=active.account, platform_id=item["platform_id"], defaults={"media_urls": item.pop("_media_urls", []), "metadata": item})
                            Snapshot.objects.update_or_create(batch=active, work=work, defaults={"data": item, "captured_at": captured})
                            from .backend.research import record_observation, task_scope
                            from .backend.subscriptions import growth_notice, notice
                            point, new_point = record_observation(active, work, item, captured)
                            if new_point:
                                growth_notice(active, work, point)
                            if created and had_samples and active.input.get('subscription_id'):
                                notice(task_scope(active), f'new:{work.pk}', '对标账号发布了新作品', 'new_work',
                                    {'title': item.get('title', ''), 'task_id': str(active.pk)}, active.account, work)
                        size = active.snapshots.count()
                    save("采集作品", progress={"current": size, "total": data["count"]})
            except CollectionError as exc:
                reason = str(exc)
                with current(payload, sink) as active:
                    from .backend.subscriptions import collection_failure
                    collection_failure(active, exc.code, reason)
                if not task.snapshots.exists():
                    raise
            if data.get('tracked_work_ids') and not reason:
                from .backend.research_runtime import refresh_work
                for tracked in task.account.works.filter(pk__in=data['tracked_work_ids']).exclude(snapshot__batch=task):
                    try:
                        refresh_work(task, tracked, client, payload, sink)
                    except CollectionError as exc:
                        reason = str(exc)
                        with current(payload, sink) as active:
                            from .backend.subscriptions import collection_failure
                            collection_failure(active, exc.code, reason)
                        if exc.code in {'auth', 'credentials', 'challenge', 'risk_control'}:
                            break
            rows = [{"id": str(s.work_id), **s.data} for s in task.snapshots.all()]
            result = rank(rows, captured)
            result.update({"requested": data["count"], "actual": len(rows), "complete": complete,
                "captured_at": captured.isoformat(), "warning": reason})
            save("completed" if complete else "partial", result)
        elif kind == "account":
            save("分析账号")
            evidence = data["evidence"]
            facts = account_statistics(evidence)
            allowed = {i["id"] for i in evidence} | {i["id"] for i in data["breakdowns"]}
            result = analysis.call_claims(task, "分析选题分布、发布频率、时长分布与表现差异。标题语义只能作为初步推测。",
                {"works": evidence, "breakdowns": data["breakdowns"], "statistics": facts}, config, allowed, cancelled=lambda: sink.cancelled)
            save("completed", {**result, "statistics": facts})
        elif kind == "transcribe":
            if data.get("reused_transcript"):
                save("completed", data["reused_transcript"])
            else:
                prefix = f"tasks/{task.pk}"
                save("获取视频")
                if data.get("media_key"):
                    path = media.path_for(data["media_key"])
                else:
                    client = DTKClient(account=task.account, check=check)
                    path = media.download_video(data.get("media_urls", []), client,
                        data["metadata"]["platform_id"], f"{prefix}/source.mp4", check)
                save("提取音频")
                audio, duration = media.extract_audio(path, prefix, check)
                def cancelled():
                    check()
                    return False
                transcript = transcribe_segments(audio, "zh", cancelled=cancelled, stage=save,
                    progress=lambda seconds: save("转写口播", progress={"current": round(seconds), "total": round(duration)}))
                output = {"text": analysis.transcript_text(transcript), "segments": transcript["segments"], "duration": duration}
                if not output["text"]:
                    output["transcript_note"] = "未识别到口播，请手工补全原文后生成改写文案，或重新转写。"
                save("completed", output)
        elif kind == "rewrite":
            save("改写文案")
            result = analysis.call_model(task, analysis.REWRITE_PROMPT,
                {"source_text": data["source_text"], "rewrite_requirements": data["rewrite_requirements"]},
                config, cancelled=lambda: sink.cancelled)
            output = analysis.validate_rewrite(result)
            with current(payload, sink) as active:
                ScriptVersion.objects.create(task=active, revision=1, content=output)
                active.stage, active.output = "completed", output
                active.save(update_fields=["stage", "output"])
            sink.emit("progress.updated", {"stage": "completed"})
        elif kind == "breakdown":
            prefix = f"tasks/{task.pk}"
            # Checkpoints survive vision/text failure; retry is explicit and creates a fresh task.
            save("获取视频")
            if data.get("media_key"):
                path = media.path_for(data["media_key"])
            else:
                client = DTKClient(account=task.account, check=check)
                path = media.download_video(data.get("media_urls", []), client,
                    data["metadata"]["platform_id"], f"{prefix}/source.mp4", check)
            save("提取关键帧")
            audio, frames, duration = media.extract(path, prefix, check)
            def cancelled():
                check()
                return False
            transcript = transcribe_segments(audio, "zh", cancelled=cancelled, stage=save,
                progress=lambda seconds: save("转写口播", progress={"current": round(seconds), "total": round(duration)}))
            segments = transcript["segments"]
            output = {"segments": segments, "frames": frames, "duration": duration, "claims": [],
                      "visual_status": "pending", "visual_note": "画面结论仅基于抽样关键帧。"}
            save("分析口播", output)
            if segments:
                result = analysis.call_claims(task, "分析开头钩子、选题、结构、论据、情绪推进和结尾。口播结论只引用 segments 中的段落 ID。",
                    {"segments": segments, "metadata": data["metadata"]}, config, {s["id"] for s in segments}, cancelled=lambda: sink.cancelled)
                output["claims"] = result["claims"]
            else:
                output["transcript_note"] = "未识别到口播，不生成文案结论。"
            save("分析画面", output)
            if config.get("vision_model"):
                try:
                    result = analysis.call_claims(task, "观察构图、开头呈现和可读字幕，并给出拍摄建议。",
                        {"frames": [{"id": f["id"], "time": f["time"]} for f in frames]}, config, {f["id"] for f in frames}, frames=frames, cancelled=lambda: sink.cancelled)
                    output["claims"] += result["claims"]
                    output["visual_status"] = "completed"
                except ValueError as exc:
                    output["visual_status"] = "failed"
                    output["visual_note"] = str(exc)
            else:
                output["visual_note"] = "未配置视觉模型，已保留转写和关键帧；配置后可重新拆解。"
            save("completed", output)
        elif kind == "topics":
            save("生成选题")
            result = analysis.call_model(task, '根据用户定位给出恰好3个新选题，返回 {"topics":[{"title":"标题","angle":"新角度","hook":"开头"}]}。' + format_instruction(data["brief"]),
                {"brief": data["brief"], "reference": data["reference"]}, config, cancelled=lambda: sink.cancelled)
            save("completed", {**analysis.validate_topics(result), "production_format": data["brief"].get("production_format", DEFAULT_FORMAT)})
        elif kind == "script":
            save("生成拍摄脚本")
            result = analysis.call_model(task, '返回 {"title":"标题","cover":"封面短句","narration":"完整口播稿","scenes":[{"time":"0–5秒","visual":"画面与执行步骤","spoken":"口播或旁白"}],"checklist":["制作准备"]}。符合用户时长及条件，资料未给出的个人经历不写成事实。' + format_instruction(data["brief"]),
                {"brief": data["brief"], "topic": data["topic"], "reference": data["reference"]}, config, cancelled=lambda: sink.cancelled)
            output = analysis.validate_script({**result, "production_format": data["brief"].get("production_format", DEFAULT_FORMAT)})
            with current(payload, sink) as active:
                ScriptVersion.objects.create(task=active, revision=1, content=output)
            save("completed", output)
        else:
            from .backend.research_runtime import execute_research
            execute_research(task, payload, sink, save, check, config)
        return {"task_id": str(task.pk)}
    except (InterruptedError, _SuspendExecution):
        raise
    except Exception as exc:
        # Keep diagnostics useful without logging exception text, locals, URLs or credentials.
        frames = traceback.extract_tb(exc.__traceback__)
        logging.getLogger(__name__).error("Douyin task=%s stage=%s error=%s stack=%s",
            payload.get("input", {}).get("task_id"), last_stage, type(exc).__name__,
            " > ".join(f"{f.name}:{f.lineno}" for f in frames))
        message = str(exc) if isinstance(exc, (ValueError, CollectionError)) else f"{last_stage}失败（{type(exc).__name__}），请检查执行服务日志后重试。"
        try:
            if isinstance(exc, CollectionError):
                with current(payload, sink) as active:
                    from .backend.subscriptions import collection_failure
                    collection_failure(active, exc.code, message)
            save("failed", error=message[:500])
        except (InterruptedError, PermissionError):
            pass
        # Never persist raw HTTP exceptions, URLs, credentials or model response bodies in generic Run events.
        raise RuntimeError(message[:500]) from None


def account_statistics(items):
    from django.utils.dateparse import parse_datetime
    dates = []
    for item in items:
        try:
            value = parse_datetime(item.get("published_at") or "")
            if value and timezone.is_aware(value):
                dates.append(value)
        except ValueError:
            pass
    durations = [i["duration"] for i in items if isinstance(i.get("duration"), (int, float)) and i["duration"] >= 0]
    span = (max(dates) - min(dates)).total_seconds() / 86400 if len(dates) > 1 else 0
    return {"sample_count": len(items), "observed_days": round(span, 2),
        "posts_per_week": round((len(dates) - 1) * 7 / span, 2) if span >= 1 else None,
        "duration_buckets": {"under_30": sum(d < 30 for d in durations), "30_to_60": sum(30 <= d < 60 for d in durations),
                             "60_to_180": sum(60 <= d < 180 for d in durations), "180_plus": sum(d >= 180 for d in durations)}}
