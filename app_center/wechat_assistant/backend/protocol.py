"""Small iLink text transport; errors deliberately exclude response bodies/tokens."""
import base64
import hashlib
import json
import logging
import secrets
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet
from django.conf import settings

BASE_URL = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "2.4.9"


class _HideWechatURLs(logging.Filter):
    def filter(self, record):
        # httpx logs complete GET URLs at INFO, including QR identifiers and
        # phone verification codes. Keep other HTTP integrations' logs intact.
        return "ilinkai.weixin.qq.com" not in record.getMessage()


logging.getLogger("httpx").addFilter(_HideWechatURLs())


class WechatError(Exception):
    def __init__(self, message="微信连接失败，请稍后重试。", *, expired=False, uncertain=False):
        super().__init__(message)
        self.expired = expired
        self.uncertain = uncertain


def seal(value):
    key = base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY + ":wechat-assistant").encode()).digest())
    return Fernet(key).encrypt(json.dumps(value).encode()).decode()


def unseal(value):
    if not value:
        return {}
    key = base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY + ":wechat-assistant").encode()).digest())
    return json.loads(Fernet(key).decrypt(value.encode()))


def trusted_base(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        raise WechatError("微信返回了无效的服务地址。") from None
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or port not in (None, 443) or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")
            or not (host == "ilinkai.weixin.qq.com" or host.endswith(".ilinkai.weixin.qq.com"))):
        raise WechatError("微信返回了不受信任的服务地址。")
    return f"https://{host}"


class WechatClient:
    def __init__(self, base_url=BASE_URL, token="", transport=None):
        self.base_url = trusted_base(base_url)
        self.token = token
        self.transport = transport

    def request(self, path, payload=None, *, params=None, timeout=15):
        headers = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": str((2 << 16) | (4 << 8) | 9)}
        if payload is not None:
            headers.update({"AuthorizationType": "ilink_bot_token", "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode()).decode()})
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
                payload = {**payload, "base_info": {"channel_version": CHANNEL_VERSION, "bot_agent": "AgentStudio/1.0.0"}}
        try:
            with httpx.Client(transport=self.transport, follow_redirects=False, timeout=timeout, trust_env=False) as client:
                response = client.request("GET" if payload is None else "POST", self.base_url + path, json=payload, params=params, headers=headers)
                if response.status_code in (401, 403):
                    raise WechatError("微信登录已失效，请重新扫码。", expired=True)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WechatError(uncertain=isinstance(exc, httpx.TransportError)) from None
        if not isinstance(data, dict):
            raise WechatError("微信响应格式异常，请重试。")
        codes = [data.get("ret", 0), data.get("errcode", 0)]
        if -14 in codes:
            raise WechatError("微信登录已失效，请重新扫码。", expired=True)
        if any(c not in (0, None) for c in codes):
            raise WechatError("微信服务暂未接受请求，请稍后重试。")
        return data

    def qrcode(self):
        return self.request("/ilink/bot/get_bot_qrcode", {"local_token_list": []}, params={"bot_type": 3})

    def login_status(self, qrcode, verify_code=""):
        params = {"qrcode": qrcode}
        if verify_code:
            params["verify_code"] = verify_code
        return self.request("/ilink/bot/get_qrcode_status", params=params, timeout=40)

    def updates(self, cursor):
        data = self.request("/ilink/bot/getupdates", {"get_updates_buf": cursor}, timeout=40)
        if not isinstance(data.get("msgs", []), list) or not isinstance(data.get("get_updates_buf", ""), str):
            raise WechatError("微信消息响应格式异常，已保留原收取进度。")
        return data

    def send(self, peer, context_token, text, client_id):
        return self.request("/ilink/bot/sendmessage", {"msg": {
            "from_user_id": "", "to_user_id": peer, "client_id": client_id,
            "message_type": 2, "message_state": 2, "context_token": context_token,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }})
