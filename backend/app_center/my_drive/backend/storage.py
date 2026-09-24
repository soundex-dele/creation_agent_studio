import os
import logging
from pathlib import Path

from django.conf import settings
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


class StorageUnavailable(APIException):
    status_code = 507
    default_detail = "存储空间不足或磁盘暂不可用，请稍后重试。"


def object_path(key):
    root = Path(settings.MY_DRIVE_ROOT).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Invalid drive object key")
    return path


def upload_key(upload, temporary=False):
    return f"{upload.space_id}/{upload.id}.{'part' if temporary else 'bin'}"


def append_chunk(upload, content):
    path = object_path(upload_key(upload, True))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("r+b" if path.exists() else "w+b") as handle:
            if handle.seek(0, os.SEEK_END) < upload.offset:
                raise StorageUnavailable("临时文件不完整，请取消此任务并重新上传。")
            # Discard an uncommitted write left by an interrupted database transaction.
            handle.truncate(upload.offset)
            handle.seek(upload.offset)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        logger.exception("Drive chunk write failed for upload %s", upload.pk)
        raise StorageUnavailable() from exc


def finalize_object(upload):
    temporary = object_path(upload_key(upload, True))
    final = object_path(upload_key(upload))
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            if final.stat().st_size != upload.size:
                raise StorageUnavailable("已完成文件大小异常，请联系管理员。")
            return
        if upload.size == 0 and not temporary.exists():
            temporary.touch()
        if not temporary.exists() or temporary.stat().st_size != upload.size:
            raise StorageUnavailable("上传文件不完整，请重试或重新上传。")
        os.replace(temporary, final)
        if os.name != "nt":
            fd = os.open(final.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except OSError as exc:
        logger.exception("Drive finalization failed for upload %s", upload.pk)
        raise StorageUnavailable() from exc
