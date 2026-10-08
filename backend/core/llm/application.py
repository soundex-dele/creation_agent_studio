"""Structured application completions through the configured system agent engine."""
import json
import logging
from tempfile import TemporaryDirectory

from django.conf import settings

from apps.enterprise.services import enforce_member_token_quota, record_usage
from core.llm.factory import build_agent_engine


class UnsupportedImageInput(RuntimeError):
    """The selected system adapter cannot deliver images to the model."""


def generate_json(*, organization, user, resource_type, resource_id,
                  instruction, content, cancelled=None, image_paths=None, on_event=None):
    """Keep application generation independent of legacy organization API routes."""
    enforce_member_token_quota(organization, user)
    if cancelled and cancelled():
        raise InterruptedError("任务已取消。")
    timeout_seconds = settings.APPLICATION_GENERATION_TIMEOUT_SECONDS
    try:
        with TemporaryDirectory(prefix="app-generation-", ignore_cleanup_errors=True) as directory:
            # Organization remains the quota/accounting boundary, not a model route.
            engine = build_agent_engine(working_directory=directory)
            if image_paths and engine.adapter_name != "codex":
                raise UnsupportedImageInput("当前系统 AI 引擎不支持关键帧图片输入，请使用支持图片输入的系统引擎。")
            options = dict(cancelled=cancelled, permission_mode="default",
                           require_tool_approval=True, timeout_seconds=timeout_seconds)
            if image_paths:
                options["image_paths"] = image_paths
            if on_event is not None:
                options["on_event"] = on_event
            response = engine.complete([
                {"role": "system", "content": instruction + "\n仅分析提供的资料，直接返回 JSON，不调用工具、不读取文件、不联网。"},
                {"role": "user", "content": content},
            ], **options)
    except (InterruptedError, UnsupportedImageInput):
        raise
    except TimeoutError:
        logging.getLogger(__name__).warning(
            "application.generation state=timed_out timeout_seconds=%s", timeout_seconds)
        raise RuntimeError(
            f"系统模型生成超时（本次时限 {timeout_seconds} 秒），请减少本次分析资料或稍后重试。"
        ) from None
    except Exception:
        message = "系统模型引擎请求失败，请检查引擎配置或登录状态后重试。"
        if image_paths:
            message = "系统模型引擎图片请求失败，请检查引擎配置、登录状态和图片输入支持后重试。"
        raise RuntimeError(message) from None
    if cancelled and cancelled():
        raise InterruptedError("任务已取消。")
    succeeded = response.success and not response.input_request
    record_usage(organization=organization, user=user, resource_type=resource_type,
                 resource_id=resource_id, usage=response.usage.model_dump(),
                 provider=engine.adapter_name, model=response.model,
                 status="success" if succeeded else "error")
    if not succeeded:
        raise RuntimeError("系统模型引擎未完成生成，请检查引擎配置或登录状态后重试。")
    try:
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        if len(raw) > 200000:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, IndexError, TypeError, AttributeError):
        raise ValueError("模型未返回有效的结构化 JSON 结果，请重试。") from None
