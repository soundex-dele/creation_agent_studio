import hashlib
import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, ValidationError
from modules.execution.application.start_runs import start_application_run
from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import CommandNotAllowed
from .models import Task, Snapshot

ACTIVE = {"queued", "running", "waiting_input", "waiting_children", "cancelling"}


class Conflict(APIException):
    status_code = 409
    default_detail = "数据已更新，请刷新后重试。"


def frozen_input(account, values):
    kind = values["kind"]
    data = json.loads(json.dumps(values, default=str))
    work = None
    if kind == "collect":
        data["source_url"] = account.source_url
    if kind == "account":
        batches = account.tasks.filter(kind="collect", snapshots__isnull=False).distinct()
        batch = get_object_or_404(batches, pk=values["batch_id"]) if values.get("batch_id") else batches.first()
        if not batch:
            raise ValidationError("请先采集账号作品。")
        data["batch_id"] = str(batch.pk)
        data["evidence"] = [{"id": str(s.work_id), **s.data} for s in Snapshot.objects.filter(batch=batch).select_related("work")]
        # Only completed breakdowns may add deeper observations to this frozen input.
        data["breakdowns"] = [{"id": str(t.pk), "work_id": str(t.work_id), "claims": t.output.get("claims", [])}
            for t in account.tasks.filter(kind="breakdown", run__status="succeeded").order_by("-created_at")[:20]]
    if kind == "breakdown":
        if not values.get("work_id"):
            raise ValidationError("请选择作品。")
        work = get_object_or_404(account.works, pk=values["work_id"])
        data.update({"metadata": work.metadata, "media_key": work.media_key, "media_urls": list(work.media_urls)})
    if kind in ("topics", "script"):
        if not values.get("source_task_id"):
            raise ValidationError("请选择已完成的拆解或选题任务。")
        expected = "breakdown" if kind == "topics" else "topics"
        source = get_object_or_404(account.tasks, pk=values["source_task_id"], kind=expected, run__status="succeeded")
        data["reference"] = {k: v for k, v in source.output.items() if k not in ("frames",)}
        if kind == "topics":
            if not source.output.get("claims"):
                raise ValidationError("所选拆解暂无可用结论，请完成口播或画面分析后再创作。")
            if not values.get("theme", "").strip() or not values.get("positioning", "").strip():
                raise ValidationError("请填写自己的账号定位和创作主题。")
            data["brief"] = {k: data[k] for k in ("positioning", "audience", "theme", "duration", "conditions")}
            if values.get("brand_profile_id"):
                from app_center.brand_library.backend.views import private_profiles
                profile = get_object_or_404(private_profiles(account.organization_id, account.owner), pk=values["brand_profile_id"])
                brand = {"id": str(profile.pk), "name": profile.name, "updated_at": profile.updated_at.isoformat(),
                         "positioning": profile.positioning, "voice": profile.voice}
                if len(json.dumps(brand, ensure_ascii=False)) > 24000:
                    raise ValidationError("品牌资料过长，请精简定位与语气资料。")
                data["brief"]["brand"] = brand
        else:
            data["brief"] = source.input["brief"]
            data["topic"] = source.output["topics"][values["topic_index"]]
            data["reference"] = source.input["reference"]
    return data, work


def start(account, values, key):
    if not key or len(key) > 160:
        raise ValidationError("请提供不超过160字符的Idempotency-Key。")
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
    prior = account.tasks.filter(request_key=key).first()
    if prior:
        if prior.request_hash != fingerprint:
            raise Conflict("同一请求键不能用于不同参数。")
        return prior
    if values["kind"] == "collect" and account.tasks.filter(kind="collect", run__status__in=ACTIVE).exists():
        raise Conflict("该账号正在采集，请等待或取消当前任务。")
    data, work = frozen_input(account, values)
    task = Task.objects.create(account=account, work=work, kind=values["kind"], request_key=key, request_hash=fingerprint, input=data)
    run, _ = start_application_run(organization_id=account.organization_id, application_id=account.application_id,
        actor=account.owner, priority=0, idempotency_key=f"dy:{task.pk}", input_data={"task_id": str(task.pk)})
    task.run = run
    task.save(update_fields=["run"])
    return task


def cancel(task):
    if task.run and task.run.status in ACTIVE - {"cancelling"}:
        try:
            submit_run_command(run_id=task.run_id, organization_id=task.account.organization_id, actor=task.account.owner,
                command_type="cancel", idempotency_key=f"dy-cancel:{task.pk}")
        except CommandNotAllowed:
            task.run.refresh_from_db()
            if task.run.status in ACTIVE:
                raise
