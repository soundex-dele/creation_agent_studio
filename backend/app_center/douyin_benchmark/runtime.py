"""Private durable jobs: input snapshots and all writes fenced by the active lease."""
from contextlib import contextmanager
from datetime import datetime
from django.db import transaction
from django.utils import timezone
from modules.tenancy.database import tenant_database_context
from modules.execution.models import Run, RunLease
from core.transcription import transcribe_segments
from .backend.models import Task, Work, Snapshot, ScriptVersion
from .backend.access import account_for
from .backend.provider import CollectionError
from .backend.collector_config import LocalDTKClient as DTKClient
from .backend.scoring import rank
from .backend import media, analysis


@contextmanager
def current(payload, sink):
    with tenant_database_context(payload["organization_id"]), transaction.atomic():
        task = Task.objects.select_for_update().select_related("account__owner", "account__organization", "account__application", "run").filter(
            pk=payload["input"]["task_id"], run_id=payload["run_id"], account__organization_id=payload["organization_id"]).first()
        run = Run.objects.select_for_update().filter(pk=payload["run_id"], status="running", current_attempt_id=payload["attempt_id"]).first()
        if sink.cancelled or not task or not run or not RunLease.objects.filter(attempt_id=payload["attempt_id"],
                released_at__isnull=True, expires_at__gt=timezone.now()).exists():
            raise InterruptedError("任务已取消或执行租约已失效。")
        if run.owner_id != task.account.owner_id or str(run.source_id) != str(task.account.application_id):
            raise PermissionError("任务不匹配。")
        account_for(task.account.owner, payload["organization_id"], task.account.application_id, task.account_id)
        yield task


def execute(payload, sink):
    def check():
        with current(payload, sink):
            pass

    def save(stage, output=None, error="", progress=None):
        with current(payload, sink) as active:
            active.stage, active.error = stage, error
            if output is not None:
                active.output = output
            if progress is not None:
                active.progress = progress
            active.save(update_fields=["stage", "error", "output", "progress"])
        sink.emit("progress.updated", {"stage": stage, **(progress or {})})

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
            complete, reason = False, ""
            try:
                for items, complete in client.pages(profile["platform_id"], data["count"]):
                    with current(payload, sink) as active:
                        for item in items:
                            work, _ = Work.objects.update_or_create(account=active.account, platform_id=item["platform_id"], defaults={"metadata": item})
                            Snapshot.objects.update_or_create(batch=active, work=work, defaults={"data": item, "captured_at": captured})
                        size = active.snapshots.count()
                    save("采集作品", progress={"current": size, "total": data["count"]})
            except CollectionError as exc:
                reason = str(exc)
                if not task.snapshots.exists():
                    raise
            rows = [{"id": str(s.work_id), **s.data} for s in task.snapshots.all()]
            result = rank(rows, captured)
            result.update({"requested": data["count"], "actual": len(rows), "complete": complete,
                "captured_at": captured.isoformat(), "warning": reason})
            save("completed" if complete else "partial", result)
        elif kind == "account":
            save("分析账号")
            evidence = data["evidence"]
            facts = account_statistics(evidence)
            result = analysis.call_model(task, "分析选题分布、发布频率、时长分布与表现差异。标题语义只能作为初步推测。" + analysis.CLAIMS_PROMPT,
                {"works": evidence, "breakdowns": data["breakdowns"], "statistics": facts}, config)
            allowed = {i["id"] for i in evidence} | {i["id"] for i in data["breakdowns"]}
            save("completed", {**analysis.validate_claims(result, allowed), "statistics": facts})
        elif kind == "breakdown":
            prefix = f"tasks/{task.pk}"
            # Checkpoints survive vision/text failure; retry is explicit and creates a fresh task.
            save("获取视频")
            if data.get("media_key"):
                path = media.path_for(data["media_key"])
            else:
                client = DTKClient(account=task.account, check=check)
                detail = client.detail(data["metadata"]["platform_id"])
                video = (detail.get("media") or {}).get("video") or {}
                if not video.get("url"):
                    raise ValueError("未取得视频文件，请在作品中补传原视频。")
                path = media.download(video["url"], f"{prefix}/source.mp4", check, headers=client.media_headers())
            save("提取关键帧")
            audio, frames, duration = media.extract(path, prefix, check)
            save("转写口播")
            def cancelled():
                check()
                return False
            transcript = transcribe_segments(audio, "zh", cancelled=cancelled,
                progress=lambda seconds: save("转写口播", progress={"current": round(seconds), "total": round(duration)}))
            segments = transcript["segments"]
            output = {"segments": segments, "frames": frames, "duration": duration, "claims": [],
                      "visual_status": "pending", "visual_note": "画面结论仅基于抽样关键帧。"}
            save("分析口播", output)
            if segments:
                result = analysis.call_model(task, "分析开头钩子、选题、结构、论据、情绪推进和结尾。" + analysis.CLAIMS_PROMPT,
                    {"segments": segments, "metadata": data["metadata"]}, config)
                output["claims"] = analysis.validate_claims(result, {s["id"] for s in segments})["claims"]
            else:
                output["transcript_note"] = "未识别到口播，不生成文案结论。"
            save("分析画面", output)
            if config.get("vision_model"):
                try:
                    result = analysis.call_model(task, "观察构图、开头呈现和可读字幕，并给出拍摄建议。" + analysis.CLAIMS_PROMPT,
                        {"frames": [{"id": f["id"], "time": f["time"]} for f in frames]}, config, frames=frames)
                    output["claims"] += analysis.validate_claims(result, {f["id"] for f in frames}, visual=True)["claims"]
                    output["visual_status"] = "completed"
                except ValueError as exc:
                    output["visual_status"] = "failed"
                    output["visual_note"] = str(exc)
            else:
                output["visual_note"] = "未配置视觉模型，已保留转写和关键帧；配置后可重新拆解。"
            save("completed", output)
        elif kind == "topics":
            save("生成选题")
            result = analysis.call_model(task, '根据用户定位给出恰好3个新选题，返回 {"topics":[{"title":"标题","angle":"新角度","hook":"开头"}]}。',
                {"brief": data["brief"], "reference": data["reference"]}, config)
            save("completed", analysis.validate_topics(result))
        else:
            save("生成拍摄脚本")
            result = analysis.call_model(task, '返回 {"title":"标题","cover":"封面短句","narration":"完整口播稿","scenes":[{"time":"0–5秒","visual":"拍摄画面","spoken":"口播"}],"checklist":["拍摄准备"]}。符合用户时长及条件，资料未给出的个人经历不写成事实。',
                {"brief": data["brief"], "topic": data["topic"], "reference": data["reference"]}, config)
            output = analysis.validate_script(result)
            with current(payload, sink) as active:
                ScriptVersion.objects.create(task=active, revision=1, content=output)
            save("completed", output)
        return {"task_id": str(task.pk)}
    except InterruptedError:
        raise
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ValueError, CollectionError)) else "处理失败，请检查服务配置后重试。"
        try:
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
