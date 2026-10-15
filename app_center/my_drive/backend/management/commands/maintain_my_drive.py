import logging
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from ...models import DriveEntry, DriveSpace, DriveUpload
from ...services import maintain_space
from ...storage import object_path, upload_key

logger = logging.getLogger(__name__)


def maintain():
    for pk in DriveSpace.objects.values_list("pk", flat=True).iterator():
        try:
            maintain_space(pk)
        except Exception:
            logger.exception("Drive maintenance failed for space %s", pk)
    # Also reclaim old physical objects orphaned by account/app cascades. Files
    # still owned by any live row are never removed, irrespective of their age.
    cutoff = (timezone.now() - timedelta(days=settings.MY_DRIVE_UPLOAD_TTL_DAYS)).timestamp()
    root = object_path("objects-placeholder").parent
    for path in root.glob("*/*"):
        if not path.resolve().is_relative_to(root):
            continue
        if path.suffix not in {".bin", ".part"} or not path.is_file() or path.stat().st_mtime >= cutoff:
            continue
        key = path.relative_to(root).as_posix()
        if DriveEntry.objects.filter(object_key=key).exists():
            continue
        try:
            upload = DriveUpload.objects.filter(pk=path.stem, space_id=path.parent.name).first()
        except (ValueError, OverflowError):
            continue
        if upload and key in {upload_key(upload), upload_key(upload, True)} and upload.state in {"uploading", "cancelling"}:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Drive orphan cleanup failed")


class Command(BaseCommand):
    help = "Retry drive deletions and expire abandoned uploads; --loop runs every minute."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            try:
                maintain()
            except Exception:
                logger.exception("Drive maintenance pass failed")
                if not options["loop"]:
                    raise
            if not options["loop"]:
                break
            time.sleep(60)
