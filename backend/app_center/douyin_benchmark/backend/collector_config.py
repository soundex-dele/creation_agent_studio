"""Personal credentials: encrypted at rest and passed only over a child stdin pipe."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from modules.tenancy.database import tenant_database_context
from django.views.decorators.debug import sensitive_variables
from .models import CollectorConfig
from .provider import DTKClient, CollectionError


def cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY + ":douyin-benchmark").encode()).digest()))


def config_for(application, owner):
    with tenant_database_context(application.organization_id):
        return CollectorConfig.objects.filter(organization_id=application.organization_id, application=application, owner=owner).first()


def public_config(config):
    return {"configured": bool(config), "user_agent": config.user_agent if config else "",
        "has_cookies": bool(config and config.encrypted_cookies),
        "screen": config.screen if config else "1920x1080", "language": config.language if config else "zh-CN",
        "timezone": config.timezone if config else "Asia/Shanghai", "updated_at": config.updated_at if config else None}


@sensitive_variables()
def private_config(config):
    if not config:
        raise CollectionError("not_configured")
    try:
        return {key: getattr(config, key) for key in ("user_agent", "screen", "language", "timezone")} | {
            "cookies": cipher().decrypt(config.encrypted_cookies.encode()).decode()}
    except InvalidToken:
        raise CollectionError("credentials") from None


@sensitive_variables()
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
            raise CollectionError(result["error"] if result["error"] in {
                "credentials", "auth", "limited", "timeout", "invalid", "unavailable",
                "content_unavailable", "signature", "challenge", "empty_response", "risk_control"} else "unavailable", diagnostic=result.get("diagnostic"))
        return result.get("data")
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


class LocalDTKClient(DTKClient):
    def __init__(self, *, account=None, application=None, owner=None, check=lambda: None):
        self.application = account.application if account is not None else application
        self.owner = account.owner if account is not None else owner
        self.check = check

    def fetch(self, path, params):
        operation = {"/api/v1/douyin/user": "profile", "/api/v1/douyin/user/posts": "pages", "/api/v1/douyin/video": "detail"}[path]
        return invoke(operation, private_config(config_for(self.application, self.owner)), params, self.check)

    def media_headers(self):
        config = config_for(self.application, self.owner)
        if not config:
            raise CollectionError("not_configured")
        return {"User-Agent": config.user_agent, "Referer": "https://www.douyin.com/"}

    def validate(self):
        return invoke("validate", private_config(config_for(self.application, self.owner)), check=self.check)
