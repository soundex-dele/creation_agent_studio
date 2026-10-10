"""Application-shared collector settings, passed over a child stdin pipe."""

from core.observability import log_operation
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from django.conf import settings
from modules.tenancy.database import tenant_database_context
from django.views.decorators.debug import sensitive_variables
from .models import CollectorConfig
from .provider import DTKClient, CollectionError


def config_for(application):
    with tenant_database_context(application.organization_id):
        return CollectorConfig.objects.filter(organization_id=application.organization_id, application=application).first()


def public_config(config):
    return {"configured": bool(config), "user_agent": config.user_agent if config else "",
        "has_cookies": bool(config and config.cookies), "cookies": config.cookies if config else "",
        "screen": config.screen if config else "1920x1080", "language": config.language if config else "zh-CN",
        "timezone": config.timezone if config else "Asia/Shanghai", "updated_at": config.updated_at if config else None}


@sensitive_variables()
def private_config(config):
    if not config:
        raise CollectionError("not_configured")
    return {key: getattr(config, key) for key in ("user_agent", "screen", "language", "timezone", "cookies")}


@sensitive_variables()
@log_operation
def invoke(operation, config, params=None, check=lambda: None):
    backend = Path(__file__).resolve().parents[3]
    executable = getattr(settings, "DOUYIN_DTK_PYTHON", os.environ.get("DOUYIN_DTK_PYTHON", "")) or str(backend / ".venv-dtk" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    check()
    try:
        process = subprocess.Popen([executable, "-X", "utf8", str(Path(__file__).resolve().parents[1] / "collector.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    except OSError:
        raise CollectionError("runtime") from None
    try:
        payload = json.dumps({"operation": operation, "config": config, "params": params or {}}, ensure_ascii=False)
        deadline = time.monotonic() + 55
        while True:
            check()
            try:
                stdout, _ = process.communicate(input=payload, timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                payload = None
                if time.monotonic() > deadline:
                    raise CollectionError("timeout")
        check()
        if process.returncode:
            raise CollectionError("runtime")
        try:
            result = json.loads(stdout)
        except (ValueError, TypeError):
            raise CollectionError("invalid") from None
        if not isinstance(result, dict):
            raise CollectionError("invalid")
        if result.get("error"):
            raise CollectionError(result["error"] if isinstance(result["error"], str) and result["error"] in {
                "credentials", "auth", "limited", "timeout", "invalid", "unavailable",
                "content_unavailable", "search_unavailable", "signature", "challenge", "empty_response", "risk_control"} else "unavailable", diagnostic=result.get("diagnostic"))
        return result.get("data")
    except CollectionError as exc:
        diagnostic = exc.diagnostic
        logging.getLogger(__name__).warning(
            "collector.failed code=%s stage=%s endpoint=%s http_status=%s upstream_error_type=%s",
            exc.code, diagnostic.get("stage", "-"), diagnostic.get("endpoint", "-"),
            diagnostic.get("http_status", "-"), diagnostic.get("error_type", "-"))
        raise
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


class LocalDTKClient(DTKClient):
    def __init__(self, *, account=None, application=None, owner=None, check=lambda: None):
        self.application = account.application if account is not None else application
        self.owner = account.owner if account is not None else owner
        self.check = check

    @log_operation
    def fetch(self, path, params):
        operation = {"/api/v1/douyin/user": "profile", "/api/v1/douyin/user/posts": "pages", "/api/v1/douyin/video": "detail", "/comments": "comments", "/replies": "replies", '/radar/hotlist': 'radar_hotlist', '/radar/search': 'radar_search'}[path]
        for attempt in range(2):
            try:
                return invoke(operation, private_config(config_for(self.application)), params, self.check)
            except CollectionError as exc:
                if attempt or exc.code not in {'timeout', 'unavailable'}:
                    raise
                for _ in range(8):
                    self.check()
                    time.sleep(.25)

    def comment_pages(self, platform_id, count, parent_id=None):
        cursor, cursors, seen = None, set(), set()
        while len(seen) < count:
            self.check()
            params = {'count': min(20, count - len(seen))}
            params.update({'item_id': platform_id, 'comment_id': parent_id} if parent_id else {'aweme_id': platform_id})
            if cursor:
                params['cursor'] = cursor
            page = self.fetch('/replies' if parent_id else '/comments', params)
            if not isinstance(page, dict) or not isinstance(page.get('items'), list):
                raise CollectionError('invalid')
            rows = []
            for row in page['items']:
                key = str(row.get('comment_id') or '')
                if not key or not isinstance(row.get('text'), str):
                    raise CollectionError('invalid')
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
                if len(seen) >= count:
                    break
            done = len(seen) >= count or not page.get('has_more')
            yield rows, done
            if done:
                return
            cursor = page.get('cursor')
            if not cursor or cursor in cursors:
                raise CollectionError('pagination')
            cursors.add(cursor)
            time.sleep(1)

    def media_headers(self):
        config = config_for(self.application)
        if not config:
            raise CollectionError("not_configured")
        return {"User-Agent": config.user_agent, "Referer": "https://www.douyin.com/"}

    @log_operation
    def validate(self):
        return invoke("validate", private_config(config_for(self.application)), check=self.check)
