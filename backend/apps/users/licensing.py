"""Offline, machine-bound license verification for desktop installations."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import platform
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from django.conf import settings


LICENSE_PREFIX = "ASL1"
SUPPORTED_LICENSE_TYPES = {"perpetual", "subscription", "trial"}


class LicenseError(ValueError):
    """A user-facing license validation error."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise LicenseError("许可证编码无效") from exc


def generate_keypair() -> tuple[str, str]:
    """Return URL-safe base64 encoded Ed25519 private/public raw keys."""

    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _b64encode(private_raw), _b64encode(public_raw)


def sign_license(payload: dict[str, Any], private_key_value: str) -> str:
    """Create a compact signed license token for the supplied payload."""

    private_raw = _b64decode(private_key_value.strip())
    if len(private_raw) != 32:
        raise LicenseError("授权私钥长度无效")
    payload_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    signature = Ed25519PrivateKey.from_private_bytes(private_raw).sign(payload_bytes)
    return f"{LICENSE_PREFIX}.{_b64encode(payload_bytes)}.{_b64encode(signature)}"


def decode_and_verify(token: str, public_key_value: str) -> dict[str, Any]:
    """Verify a compact token signature and return its JSON payload."""

    compact = "".join(str(token or "").split())
    parts = compact.split(".")
    if len(parts) != 3 or parts[0] != LICENSE_PREFIX:
        raise LicenseError("许可证格式无效")
    if not public_key_value.strip():
        raise LicenseError("应用未配置许可证公钥")
    public_raw = _b64decode(public_key_value.strip())
    if len(public_raw) != 32:
        raise LicenseError("许可证公钥配置无效")
    payload_bytes = _b64decode(parts[1])
    signature = _b64decode(parts[2])
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, payload_bytes)
    except (InvalidSignature, ValueError) as exc:
        raise LicenseError("许可证签名无效") from exc
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseError("许可证内容无效") from exc
    if not isinstance(payload, dict):
        raise LicenseError("许可证内容无效")
    return payload


def _parse_time(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise LicenseError(f"许可证缺少 {field_name}")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise LicenseError(f"许可证 {field_name} 格式无效") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def validate_license(
    token: str,
    *,
    expected_machine_code: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate signature, product, machine binding and validity period."""

    payload = decode_and_verify(token, settings.LICENSE_PUBLIC_KEY)
    if payload.get("version") != 1:
        raise LicenseError("不支持此许可证版本")
    if payload.get("product") != settings.LICENSE_PRODUCT_ID:
        raise LicenseError("许可证不适用于此产品")
    current_machine = expected_machine_code or machine_code()
    if payload.get("machine_code") != current_machine:
        raise LicenseError("许可证与当前电脑不匹配，请重新申请授权")
    license_type = payload.get("license_type")
    if license_type not in SUPPORTED_LICENSE_TYPES:
        raise LicenseError("许可证类型无效")
    if not isinstance(payload.get("license_id"), str) or not payload["license_id"].strip():
        raise LicenseError("许可证缺少编号")

    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued_at = _parse_time(payload.get("issued_at"), "issued_at")
    if issued_at > current_time.replace(microsecond=0):
        raise LicenseError("系统时间早于许可证签发时间，请校准系统时间")
    expires_at_value = payload.get("expires_at")
    if license_type in {"subscription", "trial"} and not expires_at_value:
        raise LicenseError("限时许可证缺少到期时间")
    if expires_at_value:
        expires_at = _parse_time(expires_at_value, "expires_at")
        if current_time >= expires_at:
            if license_type == "trial":
                raise LicenseError("试用许可证已过期")
            raise LicenseError("许可证已过期")
    return payload


def _windows_machine_id() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            access,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip()
    except OSError:
        return None


def _portable_machine_id() -> str:
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return f"{platform.node()}:{uuid.getnode():012x}"


def machine_code() -> str:
    """Return a stable, non-reversible identifier suitable for user sharing."""

    source = _windows_machine_id() or _portable_machine_id()
    digest = hashlib.sha256(
        f"{settings.LICENSE_PRODUCT_ID}\0{source}".encode("utf-8")
    ).hexdigest().upper()[:24]
    return "AS-" + "-".join(re.findall(r".{1,4}", digest))


def license_file_path() -> Path | None:
    value = str(getattr(settings, "LICENSE_FILE_PATH", "") or "").strip()
    return Path(value) if value else None


def save_installed_license(token: str) -> None:
    path = license_file_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(token.split()) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_installed_license() -> str | None:
    path = license_file_path()
    if path is None or not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None
