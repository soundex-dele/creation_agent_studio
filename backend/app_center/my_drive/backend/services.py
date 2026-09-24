import hashlib
import logging
import mimetypes
import uuid
from datetime import timedelta
from pathlib import PurePosixPath

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from .models import DriveChunk, DriveEntry, DriveSpace, DriveUpload
from .storage import append_chunk, finalize_object, object_path, upload_key

logger = logging.getLogger(__name__)


class Conflict(APIException):
    status_code = 409
    default_detail = "文件状态已变化，请刷新后重试。"


def lock_space(space_id):
    if connection.vendor == "sqlite":
        # SQLite ignores SELECT FOR UPDATE. Acquire its writer lock before any
        # reads or filesystem writes, so concurrent requests cannot overwrite
        # a chunk whose database transaction has already committed.
        DriveSpace.objects.filter(pk=space_id).update(owner_id=F("owner_id"))
    return DriveSpace.objects.select_for_update().get(pk=space_id)


def entries(space, application):
    return DriveEntry.objects.filter(space=space, application=application)


def folder_for(queryset, pk):
    if pk is None:
        return None
    return get_object_or_404(queryset, pk=pk, kind="folder", trash_batch=None, purge_pending=False)


def usage(space):
    used = DriveEntry.objects.filter(space=space).aggregate(n=Sum("size"))["n"] or 0
    reserved = DriveUpload.objects.filter(space=space, state__in=["uploading", "cancelling"]).aggregate(n=Sum("size"))["n"] or 0
    return {"used": used, "reserved": reserved, "limit": settings.MY_DRIVE_QUOTA_BYTES,
            "max_file_size": settings.MY_DRIVE_MAX_FILE_BYTES}


def available_name(queryset, parent, name, exclude=None):
    siblings = queryset.filter(parent=parent, trash_batch=None, purge_pending=False)
    if exclude:
        siblings = siblings.exclude(pk=exclude)
    names = set(siblings.values_list("name", flat=True))
    if name not in names:
        return name
    suffix = PurePosixPath(name).suffix[:40]
    stem = name[:-len(suffix)] if suffix else name
    index = 1
    while True:
        tail = f" ({index}){suffix}"
        candidate = stem[:240 - len(tail)] + tail
        if candidate not in names:
            return candidate
        index += 1


def subtree(queryset, root):
    result, frontier = {root.id}, {root.id}
    while frontier:
        frontier = set(queryset.filter(parent_id__in=frontier).values_list("id", flat=True)) - result
        result.update(frontier)
    return result


@transaction.atomic
def create_folder(space, application, data):
    lock_space(space.pk)
    qs = entries(space, application)
    parent = folder_for(qs, data.get("parent"))
    return qs.create(space=space, application=application, parent=parent, kind="folder",
                     name=available_name(qs, parent, data["name"]))


@transaction.atomic
def create_upload(space, application, data):
    lock_space(space.pk)
    if data["size"] > settings.MY_DRIVE_MAX_FILE_BYTES:
        raise ValidationError("文件超过单文件大小上限。")
    totals = usage(space)
    if totals["used"] + totals["reserved"] + data["size"] > totals["limit"]:
        raise ValidationError("网盘容量不足，请清理回收站或取消未完成的上传。")
    parent = folder_for(entries(space, application), data.get("parent"))
    return DriveUpload.objects.create(space=space, application=application, parent=parent,
        name=data["name"], size=data["size"], last_modified=data["last_modified"],
        chunk_size=settings.MY_DRIVE_CHUNK_BYTES)


@transaction.atomic
def write_chunk(space, application, pk, offset, digest, content):
    lock_space(space.pk)
    upload = get_object_or_404(DriveUpload, pk=pk, space=space, application=application)
    if upload.state != "uploading":
        raise Conflict("该上传任务已结束。")
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValidationError("分片校验失败，请重新上传该分片。")
    prior = upload.chunks.filter(offset=offset).first()
    if prior:
        if prior.sha256 != digest or prior.size != len(content):
            raise Conflict("分片内容与已确认数据不同。")
        upload.save(update_fields=["updated_at"])
        return upload
    if offset != upload.offset:
        raise Conflict("上传进度已变化，请读取已确认进度后续传。")
    expected = min(upload.chunk_size, upload.size - upload.offset)
    if not content or len(content) != expected:
        raise ValidationError("分片大小不正确。")
    append_chunk(upload, content)
    DriveChunk.objects.create(upload=upload, offset=offset, size=len(content), sha256=digest)
    upload.offset += len(content)
    upload.save(update_fields=["offset", "updated_at"])
    return upload


@transaction.atomic
def complete_upload(space, application, pk):
    lock_space(space.pk)
    upload = get_object_or_404(DriveUpload, pk=pk, space=space, application=application)
    if upload.state == "completed":
        return upload
    if upload.state != "uploading" or upload.offset != upload.size:
        raise Conflict("上传尚未完成或已取消。")
    qs = entries(space, application)
    parent = qs.filter(pk=upload.parent_id, trash_batch=None, purge_pending=False).first()
    # The filesystem rename is atomic but not transactional. Its destination is
    # deterministic: a retry after DB failure adopts the already renamed object.
    finalize_object(upload)
    entry = qs.create(space=space, application=application, parent=parent, kind="file",
        name=available_name(qs, parent, upload.name), size=upload.size,
        media_type=mimetypes.guess_type(upload.name)[0] or "application/octet-stream",
        object_key=upload_key(upload))
    upload.entry = entry
    upload.state = "completed"
    upload.save(update_fields=["entry", "state", "updated_at"])
    return upload


@transaction.atomic
def cancel_upload(space, application, pk):
    lock_space(space.pk)
    upload = get_object_or_404(DriveUpload, pk=pk, space=space, application=application)
    if upload.state == "completed":
        raise Conflict("上传已经完成，请在文件列表中删除。")
    if upload.state == "cancelled":
        return upload
    upload.state = "cancelling"
    upload.save(update_fields=["state", "updated_at"])
    return upload


@transaction.atomic
def apply_action(space, application, data):
    lock_space(space.pk)
    qs = entries(space, application)
    selected = list(qs.filter(pk__in=data["ids"], purge_pending=False))
    if len(selected) != len(set(data["ids"])):
        raise ValidationError("部分文件不存在，请刷新列表。")
    action = data["action"]
    if action == "rename" and (len(selected) != 1 or not data.get("name")):
        raise ValidationError("请选择一个文件并输入新名称。")
    if action == "move" and "parent" not in data:
        raise ValidationError("请选择目标文件夹。")
    parent = folder_for(qs, data.get("parent")) if action == "move" else None
    chosen = {item.id for item in selected}
    # Selecting both parent and child should operate on the tree exactly once.
    descendants = set()
    for item in selected:
        descendants.update(subtree(qs, item) - {item.id})
    if action != "restore":
        selected = [item for item in selected if item.id not in chosen.intersection(descendants)]
    else:
        def depth(item):
            result = 0
            while item.parent_id:
                result += 1
                item = item.parent
            return result
        selected.sort(key=depth)
    for item in selected:
        if action in {"rename", "move", "trash"} and item.trash_batch:
            raise Conflict("请先从回收站恢复文件。")
        if action in {"restore", "purge"} and not item.trash_root:
            raise Conflict("请从回收站选择完整的删除项。")
        if action in {"rename", "move"}:
            if action == "move":
                if parent and parent.id in subtree(qs, item):
                    raise ValidationError("不能移动到自身或子文件夹中。")
                item.parent = parent
            item.name = available_name(qs, item.parent, data.get("name", item.name) if action == "rename" else item.name, item.id)
            item.save(update_fields=["parent", "name", "updated_at"])
        elif action == "trash":
            batch = uuid.uuid4()
            qs.filter(pk__in=subtree(qs, item), trash_batch=None).update(trash_batch=batch, updated_at=timezone.now())
            qs.filter(pk=item.pk).update(trash_root=True)
        elif action == "restore":
            item.parent = qs.filter(pk=item.parent_id, trash_batch=None, purge_pending=False).first()
            item.name = available_name(qs, item.parent, item.name)
            item.save(update_fields=["parent", "name", "updated_at"])
            qs.filter(trash_batch=item.trash_batch).update(trash_batch=None, trash_root=False, updated_at=timezone.now())
        elif action == "purge":
            qs.filter(pk__in=subtree(qs, item)).update(purge_pending=True)


def maintain_space(space_id):
    """Idempotent: failures retain rows/quota so later maintenance can retry."""
    with transaction.atomic():
        space = lock_space(space_id)
        expiry = timezone.now() - timedelta(days=settings.MY_DRIVE_UPLOAD_TTL_DAYS)
        DriveUpload.objects.filter(space=space, state="uploading", updated_at__lt=expiry).update(state="cancelling")
        for upload in DriveUpload.objects.filter(space=space, state="cancelling").order_by("created_at")[:100]:
            try:
                object_path(upload_key(upload, True)).unlink(missing_ok=True)
                object_path(upload_key(upload)).unlink(missing_ok=True)
            except OSError:
                logger.warning("Drive upload cleanup will retry: %s", upload.pk, exc_info=True)
                continue
            upload.chunks.all().delete()
            upload.state = "cancelled"
            upload.save(update_fields=["state", "updated_at"])
        for item in DriveEntry.objects.filter(space=space, purge_pending=True).order_by("created_at")[:100]:
            try:
                if item.object_key:
                    object_path(item.object_key).unlink(missing_ok=True)
            except OSError:
                logger.warning("Drive file cleanup will retry: %s", item.pk, exc_info=True)
                continue
            item.delete()
        DriveUpload.objects.filter(space=space, state__in=["cancelled", "completed"], updated_at__lt=expiry).delete()
