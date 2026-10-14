"""Structured application completions through the configured system agent engine."""
import json
import logging
from tempfile import TemporaryDirectory

from django.conf import settings

from apps.enterprise.services import enforce_member_token_quota, record_usage
from core.llm.factory import build_agent_engine


class UnsupportedImageInput(RuntimeError):
    """The selected system adapter cannot deliver images to the model."""


class GenerationError(RuntimeError):
    """Safe, actionable error information without provider payloads or secrets."""
    def __init__(self, message, *, code='engine_failed', retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def engine_failure(error, *, requires_input=False):
    # Provider text is used only for classification. Never send raw text to the
    # client: it can include credentials, request bodies or private source code.
    value = str(error or '').lower()
    if requires_input:
        return GenerationError('系统模型引擎等待交互确认，未能完成自动生成。请检查引擎状态后重试。', code='input_required')
    if any(term in value for term in ('at capacity', 'server_overloaded', 'overloaded', '503', 'temporarily unavailable')):
        return GenerationError('模型服务繁忙，暂时无法接收请求，请稍后重试。', code='engine_overloaded', retryable=True)
    if any(term in value for term in ('quota exceeded', 'insufficient_quota', 'usage limit')):
        return GenerationError('模型服务的可用额度不足，请检查额度或等待额度恢复后重试。', code='provider_quota_exceeded')
    if any(term in value for term in ('rate limit', 'rate_limit', '429', 'too many requests')):
        return GenerationError('模型请求过于频繁，暂时受到限流，请稍后重新生成。', code='rate_limited')
    if any(term in value for term in ('401', 'unauthorized', 'authentication', 'not logged in', 'invalid api key')):
        return GenerationError('模型登录或认证已失效，请重新登录或检查引擎认证配置。', code='authentication_failed')
    if any(term in value for term in ('context_length', 'context window', 'too many tokens', 'request too large')):
        return GenerationError('本次资料超过模型上下文容量，请缩小分析范围后重试。', code='context_limit')
    return GenerationError('系统模型引擎未完成生成，请检查引擎状态或登录状态后重试。')


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
            if engine.adapter_name == "codex":
                options["final_response_only"] = True
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
        raise GenerationError(
            f"系统模型生成超时（本次时限 {timeout_seconds} 秒），请减少本次分析资料或稍后重试。", code='timeout'
        ) from None
    except Exception as exc:
        failure = engine_failure(exc)
        if failure.code != 'engine_failed':
            raise failure from None
        message = "系统模型引擎请求失败，请检查引擎配置或登录状态后重试。"
        if image_paths:
            message = "系统模型引擎图片请求失败，请检查引擎配置、登录状态和图片输入支持后重试。"
        raise GenerationError(message) from None
    if cancelled and cancelled():
        raise InterruptedError("任务已取消。")
    succeeded = response.success and not response.input_request
    record_usage(organization=organization, user=user, resource_type=resource_type,
                 resource_id=resource_id, usage=response.usage.model_dump(),
                 provider=engine.adapter_name, model=response.model,
                 status="success" if succeeded else "error")
    if not succeeded:
        failure = engine_failure(response.error, requires_input=bool(response.input_request))
        logging.getLogger(__name__).warning('application.generation state=failed code=%s', failure.code)
        raise failure
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
