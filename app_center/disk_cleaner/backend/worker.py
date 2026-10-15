"""One host-local worker; only explicitly queued tasks may touch the filesystem."""
from datetime import datetime, timezone as dt_timezone
import os
from pathlib import Path
import time
from types import SimpleNamespace

from django.db import close_old_connections
from django.utils import timezone
from modules.tenancy.database import tenant_database_context

from . import filesystem as fs
from .access import application_for
from .models import CleanerEntry, CleanerHost, CleanerTask

ACTIVE = ("queued", "running")


class Cancelled(Exception):
    pass


def authorize(task):
    task.owner.refresh_from_db()
    # Only authorization needs product-table RLS context. Do not hold a DB
    # transaction across scanning or irreversible filesystem operations.
    with tenant_database_context(task.organization_id):
        application_for(SimpleNamespace(user=task.owner, method="POST"), task.organization_id, task.application_id)
    if task.host != fs.host_id():
        raise fs.UnsafePath("任务不属于当前主机。")


class Progress:
    def __init__(self, task):
        self.task = task
        self.last = 0

    def tick(self, force=False):
        if not force and time.monotonic() - self.last < .5:
            return
        self.last = time.monotonic()
        if CleanerTask.objects.get(pk=self.task.pk).cancel_requested:
            raise Cancelled()
        authorize(self.task)
        self.task.heartbeat_at = timezone.now()
        self.task.save(update_fields=["processed", "total_bytes", "skipped", "deleted_bytes", "heartbeat_at"])
        heartbeat(self.task.host)


def heartbeat(host):
    # UPDATE first avoids SQLite's deferred read -> write transaction upgrade,
    # which can fail immediately when other application workers are writing.
    now = timezone.now()
    if not CleanerHost.objects.filter(pk=host).update(heartbeat_at=now):
        CleanerHost.objects.get_or_create(pk=host, defaults={"heartbeat_at": now})


def scan(task, progress):
    params = task.parameters
    mode = params["mode"]
    root = fs.validate_root(params["root"], mode)
    identity = fs.snapshot(root)
    if any(identity[k] != params["root_identity"][k] for k in ("volume", "index")):
        raise fs.UnsafePath("扫描目录已经替换，请重新提交。")
    pending = [root]
    directory_sizes = {root: 0}
    batch = []
    visited = 0
    cutoff = time.time() - 7 * 86400
    try:
        while pending:
            progress.tick()
            directory = pending.pop()
            try:
                fs.no_reparse(directory)
                if fs.protected(directory, root if mode == "cache" else None):
                    task.skipped += 1
                    continue
                with os.scandir(directory) as items:
                    for item in items:
                        visited += 1
                        if visited > 500000:
                            task.message = "达到单次 500000 条目上限，结果不完整；请选择更小的子目录继续扫描。"
                            return
                        progress.tick()
                        path = Path(item.path)
                        try:
                            fs.no_reparse(path)
                            if fs.protected(path, root if mode == "cache" else None):
                                task.skipped += 1
                                continue
                            if item.is_dir(follow_symlinks=False):
                                pending.append(path)
                                directory_sizes[path] = 0
                                continue
                            if not item.is_file(follow_symlinks=False):
                                task.skipped += 1
                                continue
                            info = item.stat(follow_symlinks=False)
                            task.processed += 1
                            task.total_bytes += info.st_size
                            parent = directory
                            while fs.under(parent, root):
                                directory_sizes[parent] = directory_sizes.get(parent, 0) + info.st_size
                                if parent == root:
                                    break
                                parent = parent.parent
                            candidate = mode == "large" and info.st_size >= params["minimum_bytes"]
                            candidate = candidate or (mode == "cache" and info.st_mtime < cutoff)
                            if candidate:
                                ident = fs.snapshot(path)
                                if ident["directory"] or ident["links"] != 1:
                                    task.skipped += 1
                                    continue
                                # Recheck the cache age against the handle snapshot, not an earlier stat.
                                modified = ident["mtime"] / 10000000 - 11644473600
                                if mode == "cache" and modified >= cutoff:
                                    task.skipped += 1
                                    continue
                                batch.append(CleanerEntry(task=task, path=str(path), parent=str(directory), kind="file",
                                    size=ident["size"], modified_at=datetime.fromtimestamp(modified, dt_timezone.utc),
                                    identity=ident, cleanable=True))
                            elif mode == "analysis":
                                batch.append(CleanerEntry(task=task, path=str(path), parent=str(directory), kind="file",
                                    size=info.st_size, modified_at=datetime.fromtimestamp(info.st_mtime, dt_timezone.utc)))
                            if len(batch) >= 200:
                                CleanerEntry.objects.bulk_create(batch)
                                batch.clear()
                        except (OSError, fs.UnsafePath, OverflowError, ValueError):
                            task.skipped += 1
            except (OSError, fs.UnsafePath):
                task.skipped += 1
    finally:
        if batch:
            CleanerEntry.objects.bulk_create(batch)
        if mode == "analysis":
            rows = [CleanerEntry(task=task, path=str(path), parent=str(path.parent), kind="directory", size=size)
                    for path, size in directory_sizes.items() if path != root]
            CleanerEntry.objects.bulk_create(rows, batch_size=200)


def cleanup(task, progress):
    if task.preview.expires_at <= timezone.now():
        raise fs.UnsafePath("清理预览已过期，请重新预览后提交。")
    task.free_before = {v["path"]: v["free"] for v in fs.volumes()}
    task.save(update_fields=["free_before"])
    # At most 1000 confirmed items. Close the read cursor before writing results,
    # so SQLite does not retain a shared read lock throughout the deletion loop.
    for result in list(task.results.select_related("entry").order_by("id")):
        progress.tick(force=True)
        if result.state != "pending":
            continue
        # Write ahead: a crash here means outcome unknown; it is never automatically retried.
        result.state = "deleting"
        result.save(update_fields=["state"])
        try:
            entry = result.entry
            if entry.task_id != task.source_id or not entry.cleanable or task.parameters["mode"] == "analysis":
                raise fs.UnsafePath("文件不属于本次可清理扫描。")
            fs.delete_verified(entry.path, task.parameters["root"], entry.identity,
                               task.parameters["root_identity"], task.parameters["mode"])
            result.state = "deleted"
            task.deleted_bytes += entry.size
        except (fs.UnsafePath, FileNotFoundError, PermissionError) as exc:
            result.state = "skipped"
            result.reason = str(exc)
            task.skipped += 1
        except OSError as exc:
            result.state = "failed"
            result.reason = str(exc)
        result.save(update_fields=["state", "reason"])
        task.processed += 1
        task.total_bytes += result.entry.size
        progress.tick(force=True)


def interrupt_previous(host):
    from django.db.models import Sum
    for task in CleanerTask.objects.filter(host=host, state="running"):
        task.results.filter(state="deleting").update(state="unknown", reason="执行进程中断，结果未知；请重新扫描，不会自动重试。")
        task.results.filter(state="pending").update(state="skipped", reason="执行进程中断，尚未处理。")
        task.state = "interrupted"
        task.message = "执行进程中断，已停止；请重新扫描后再清理。"
        task.finished_at = timezone.now()
        if task.kind == "cleanup":
            task.deleted_bytes = task.results.filter(state="deleted").aggregate(size=Sum("entry__size"))["size"] or 0
            task.processed = task.results.exclude(reason="执行进程中断，尚未处理。").count()
        task.save(update_fields=["state", "message", "finished_at", "deleted_bytes", "processed"])


def process_next(host):
    """Caller must hold the machine-wide lock, including with SQLite."""
    close_old_connections()
    heartbeat(host)
    task = CleanerTask.objects.filter(host=host, state="queued").select_related("owner", "preview").order_by("created_at").first()
    if task is None:
        return False
    task.state = "running"
    task.heartbeat_at = timezone.now()
    task.save(update_fields=["state", "heartbeat_at"])
    try:
        progress = Progress(task)
        progress.tick(force=True)
        if task.kind == "scan":
            scan(task, progress)
        else:
            cleanup(task, progress)
        progress.tick(force=True)
        task.state = "completed"
    except Cancelled:
        task.state = "cancelled"
        task.message = "已停止；已经删除的文件无法恢复。" if task.kind == "cleanup" else "扫描已取消。"
    except Exception as exc:
        task.state = "failed"
        task.message = str(exc)
    finally:
        if task.kind == "cleanup":
            task.results.filter(state="pending").update(state="skipped", reason="任务已停止，尚未处理。")
            task.results.filter(state="deleting").update(state="unknown", reason="结果未知，请重新扫描；不会自动重试。")
            try:
                task.free_after = {v["path"]: v["free"] for v in fs.volumes()}
            except OSError:
                task.free_after = {}
        task.finished_at = timezone.now()
        task.save()
    return True
