"""Volcengine bidirectional-independent HTTP streaming TTS adapter.

Protocol: https://www.volcengine.com/docs/6561/1598757
Only the official endpoint is used; credentials never enter task snapshots.
"""
import base64
import json
import uuid
import requests
from .backend.models import AnimationSpeechConfig
from apps.enterprise.services import resolve_secret

ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


def synthesize(application, text, voice, speed, *, cancelled=lambda: False):
    config = AnimationSpeechConfig.objects.for_organization(application.organization_id).filter(application=application, enabled=True).first()
    if not config: raise RuntimeError("尚未配置豆包配音，请联系组织管理员或上传录音。")
    if voice not in [v.get("id") for v in config.voices]: raise RuntimeError("音色未在组织配音配置中启用。")
    reference = application.organization.secret_references.filter(name=config.secret_ref).first()
    if not reference: raise RuntimeError("配音密钥引用未配置。")
    secret = resolve_secret(reference)
    headers = {"X-Api-Resource-Id": config.resource_id, "X-Api-Request-Id": str(uuid.uuid4())}
    headers.update({"X-Api-App-Id": config.app_id, "X-Api-Access-Key": secret} if config.app_id else {"X-Api-Key": secret})
    body = {"user": {"uid": "animation-studio"}, "req_params": {"text": text, "speaker": voice,
        "audio_params": {"format": "mp3", "sample_rate": 24000, "speech_rate": round((speed - 1) * 100)}}}
    output = bytearray()
    if cancelled(): raise InterruptedError("配音已取消。")
    try:
        with requests.post(ENDPOINT, headers=headers, json=body, stream=True, timeout=(10, 30)) as response:
            if response.status_code != 200: raise RuntimeError(f"豆包配音请求失败（HTTP {response.status_code}），请检查服务配置。")
            finished = False
            for raw in response.iter_lines():
                if cancelled(): raise InterruptedError("配音已取消。")
                if not raw: continue
                item = json.loads(raw)
                code = item.get("code")
                if code not in (0, 20000000): raise RuntimeError(f"豆包配音失败（服务代码 {code}），请检查音色权限和额度。")
                if item.get("data"): output.extend(base64.b64decode(item["data"], validate=True))
                if len(output) > 50 * 1024 * 1024: raise RuntimeError("配音结果超过 50 MB。")
                if code == 20000000: finished = True; break
            if not finished or not output: raise RuntimeError("配音响应未完成，请重试。")
    except requests.RequestException:
        raise RuntimeError("豆包配音连接失败或超时，请检查网络后重试。") from None
    except (ValueError, TypeError):
        raise RuntimeError("豆包配音返回了无效数据。") from None
    return bytes(output)
