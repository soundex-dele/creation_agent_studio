"""Explicit real-network probe, without creating application data or logging credentials."""
import json
import tempfile
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from app_center.douyin_benchmark.backend.provider import source_url, CollectionError
from app_center.douyin_benchmark.backend.collector_config import LocalDTKClient
from app_center.douyin_benchmark.backend.access import account_for
from modules.tenancy.database import tenant_database_context
from django.contrib.auth import get_user_model
from app_center.douyin_benchmark.backend.media import download, probe
from django.test.utils import override_settings


class Command(BaseCommand):
    help = "Verify personal DTK source configuration against a public account (two pages and one video)."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True)
        parser.add_argument("--application", required=True, type=int)
        parser.add_argument("--owner", required=True, type=int)
        parser.add_argument("--account", required=True, help="Saved account UUID")
        parser.add_argument('--comments', action='store_true', help='Also verify a bounded first page of normalized comments.')

    def handle(self, *args, **options):
        try:
            with tenant_database_context(options["organization"]):
                account = account_for(get_user_model().objects.get(pk=options["owner"]), options["organization"], options["application"], options["account"])
                client = LocalDTKClient(application=account.application, owner=account.owner)
                url = source_url(account.source_url)
            profile = client.profile(url)
            pages, items = 0, []
            for entries, complete in client.pages(profile["platform_id"], 50):
                pages += 1
                items.extend(entries)
                if pages >= 2:
                    break
            if pages < 2:
                raise ValueError("该账号不足两页作品，请选择至少有21条公开作品的账号。")
            video = next((item for item in items if item["kind"] == "video" and item.get("duration") is not None and item["duration"] <= 600), None)
            if not video:
                raise ValueError("前两页没有10分钟内可供验证的视频。")
            detail = client.detail(video["platform_id"])
            comment_count = None
            if options['comments']:
                comment_rows, _ = next(client.comment_pages(video['platform_id'], 20))
                comment_count = len(comment_rows)
            media = (detail.get("media") or {}).get("video") or {}
            if not media.get("url"):
                raise ValueError("没有可下载的视频地址。")
            with tempfile.TemporaryDirectory(prefix="douyin-probe-") as directory, override_settings(DOUYIN_MEDIA_ROOT=Path(directory)):
                path = download(media["url"], "probe/source.mp4", lambda: None, headers=client.media_headers())
                duration = probe(path)
            self.stdout.write(json.dumps({"verified": True, "pages": pages, "works": len(items), "video_duration": duration, 'comments': comment_count,
                "metrics_present": {k: sum(item[k] is not None for item in items) for k in ("likes", "comments", "collects", "shares")}}, ensure_ascii=False))
        except (CollectionError, ValueError) as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            raise CommandError("真实采集验证失败，请检查服务、登录状态和网络。") from None
