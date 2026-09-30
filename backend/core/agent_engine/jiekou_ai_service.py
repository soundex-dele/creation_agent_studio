from __future__ import annotations

import logging
import time

import requests
from core.observability import log_operation

from .models import (
    AsyncTask,
    JieKouConfig,
    LLMResponse,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class JieKouAIService:
    """JieKou AI HTTP provider.

    Wraps the following endpoints behind a single ``JieKouConfig``:

    - **Chat**       ``POST /openai/v1/chat/completions``
    - **List models** ``GET  /openai/v1/models``
    - **Image**      ``POST /v3/async/qwen-image-txt2img``
    - **Task query**  ``GET  /v3/async/task-result``
    """

    def __init__(self, config: JieKouConfig) -> None:
        self._config = config
        self._total_usage = TokenUsage()
        logger.info("JieKouAIService initialized, model=%s", config.model)

    # ─── Chat ────────────────────────────────────────────────────────

    @log_operation
    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs,
    ) -> LLMResponse | requests.Response:
        """Send a chat completion request.

        Args:
            messages: OpenAI-style message list.
            stream: If *True*, return the raw ``requests.Response``
                    for the caller to iterate SSE lines.
            **kwargs: Forwarded directly into the JSON body
                     (e.g. ``tools``, ``response_format``).

        Returns:
            Parsed :class:`LLMResponse`, or raw ``requests.Response``
            when *stream=True*.
        """
        url = f"{self._base}/openai/v1/chat/completions"
        body: dict = {
            "model": model or self._config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._config.temperature,
            "max_tokens": max_tokens or self._config.max_tokens,
            "stream": stream,
            **kwargs,
        }
        logger.info("Chat request: model=%s, stream=%s, messages=%d",
                     body["model"], stream, len(messages))
        return self._post(url, body, stream=stream, parse=self._parse_chat)

    # ─── Models ──────────────────────────────────────────────────────

    @log_operation
    def list_models(self) -> list[dict]:
        """Return the model list from the API.

        Each item is a dict with at least ``id``, ``title``, ``description``.
        On failure returns an empty list.
        """
        url = f"{self._base}/openai/v1/models"
        logger.info("provider.models state=fetching")
        try:
            resp = requests.get(url, headers=self._headers(),
                                timeout=self._config.timeout)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            logger.info("Fetched %d models", len(data))
            return data
        except Exception as exc:
            logger.warning("provider.models state=failed", exc_info=True)
            return []

    # ─── Image (async) ───────────────────────────────────────────────

    @log_operation
    def submit_image(
        self,
        prompt: str,
        *,
        size: str = "1024*1024",
    ) -> AsyncTask:
        """Submit an async image generation task (Qwen-Image txt2img).

        Returns an :class:`AsyncTask` with ``task_id`` set.
        Poll the result with :meth:`get_task_result` or
        :meth:`wait_for_task`.
        """
        url = f"{self._base}/v3/async/qwen-image-txt2img"
        body = {"prompt": prompt, "size": size}
        logger.info("provider.image state=submitting size=%s", size)
        return self._post(url, body, parse=self._parse_async_submit)

    # ─── Task query (shared by image / video / audio) ────────────────

    def get_task_result(self, task_id: str) -> AsyncTask:
        """Query the unified task-result endpoint.

        Works for image, video, and audio async tasks.
        """
        url = f"{self._base}/v3/async/task-result"
        return self._get(url, params={"task_id": task_id},
                         parse=self._parse_task_result)

    @log_operation
    def wait_for_task(self, task_id: str, max_wait: float = 600) -> AsyncTask:
        """Poll ``get_task_result`` until the task completes or times out."""
        logger.info("Waiting for task %s (max %.0fs)", task_id, max_wait)
        deadline = time.time() + max_wait
        poll_count = 0
        while time.time() < deadline:
            task = self.get_task_result(task_id)
            poll_count += 1
            if task.status in ("completed", "failed"):
                logger.info("Task %s finished: status=%s, polls=%d",
                            task_id, task.status, poll_count)
                return task
            time.sleep(self._config.poll_interval)
        logger.warning("Task %s timed out after %d polls", task_id, poll_count)
        return AsyncTask(task_id=task_id, status="failed",
                         error=f"Timed out after {max_wait}s")

    def submit_image_and_wait(
        self,
        prompt: str,
        *,
        size: str = "1024*1024",
        max_wait: float = 300,
    ) -> AsyncTask:
        """Submit an image task and block until done."""
        task = self.submit_image(prompt, size=size)
        if not task.success:
            return task
        return self.wait_for_task(task.task_id, max_wait=max_wait)

    # ─── Usage ───────────────────────────────────────────────────────

    @property
    def usage(self) -> TokenUsage:
        return self._total_usage

    # ─── Properties ──────────────────────────────────────────────────

    @property
    def _base(self) -> str:
        return self._config.base_url.rstrip("/")

    # ─── HTTP helpers ────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, url, body, *, stream=False, parse):
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                logger.info("provider.request method=POST state=started attempt=%s", attempt + 1)
                resp = requests.post(
                    url, json=body, headers=self._headers(),
                    timeout=self._config.timeout, stream=stream,
                )
                if stream:
                    resp.raise_for_status()
                    return resp
                logger.info("provider.request method=POST state=received http_status=%s", resp.status_code)
                if not resp.ok:
                    return _err(parse, resp=resp)
                return parse(resp.json())
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                logger.warning("provider.request method=POST state=connection_failed attempt=%s max_attempts=%s",
                               attempt + 1, self._config.max_retries + 1, exc_info=True)
                if attempt < self._config.max_retries:
                    time.sleep(attempt + 1)
        return _err(parse, last_error=last_error)

    def _get(self, url, *, parse, params: dict | None = None):
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                logger.debug("provider.request method=GET state=started attempt=%s", attempt + 1)
                resp = requests.get(
                    url, headers=self._headers(), params=params,
                    timeout=self._config.timeout,
                )
                logger.debug("provider.request method=GET state=received http_status=%s", resp.status_code)
                if not resp.ok:
                    return _err(parse, resp=resp)
                return parse(resp.json())
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                logger.warning("provider.request method=GET state=connection_failed attempt=%s max_attempts=%s",
                               attempt + 1, self._config.max_retries + 1, exc_info=True)
                if attempt < self._config.max_retries:
                    time.sleep(attempt + 1)
        return _err(parse, last_error=last_error)

    # ─── Response parsers ────────────────────────────────────────────

    def _parse_chat(self, data: dict) -> LLMResponse:
        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content") or ""
            reasoning = message.get("reasoning_content")
            if reasoning:
                content = f"<think/>\n{reasoning}\n\n{content}"

            raw = data.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=raw.get("prompt_tokens", 0),
                completion_tokens=raw.get("completion_tokens", 0),
                total_tokens=raw.get("total_tokens", 0),
            )
            self._total_usage = self._total_usage + usage
            logger.info("Chat response: model=%s, tokens=%s, content_len=%d",
                         data.get("model", ""), usage, len(content))
            return LLMResponse(content=content, usage=usage,
                                model=data.get("model", self._config.model))
        except (KeyError, IndexError, TypeError) as exc:
            logger.exception("provider.chat state=invalid_response")
            return LLMResponse(content="", usage=TokenUsage(),
                                model=self._config.model, success=False,
                                error=f"Parse error: {exc}")

    def _parse_async_submit(self, data: dict) -> AsyncTask:
        task_id = data.get("task_id", "")
        if not task_id:
            logger.error("provider.task state=invalid_response reason=missing_task_id")
            return AsyncTask(success=False,
                             error=f"No task_id in response: {data}")
        logger.info("Async task submitted: task_id=%s", task_id)
        return AsyncTask(task_id=task_id, status="pending")

    def _parse_task_result(self, data: dict) -> AsyncTask:
        task = data.get("task", {})
        images = data.get("images", [])
        videos = data.get("videos", [])

        raw_status = task.get("status", "").upper()
        status_map = {
            "TASK_STATUS_QUEUED": "queued",
            "TASK_STATUS_PROCESSING": "processing",
            "TASK_STATUS_SUCCEED": "completed",
            "TASK_STATUS_FAILED": "failed",
        }
        status = status_map.get(raw_status, raw_status.lower())

        result = AsyncTask(
            task_id=task.get("task_id", ""),
            status=status,
            reason=task.get("reason"),
            progress_percent=task.get("progress_percent"),
            image_urls=[i.get("image_url", "") for i in images if i.get("image_url")],
            video_urls=[v.get("video_url", "") for v in videos if v.get("video_url")],
            audio_urls=[a.get("audio_url", "") for a in data.get("audios", []) if a.get("audio_url")],
        )
        logger.debug("Task result: id=%s, status=%s (raw=%s), images=%d, videos=%d",
                      result.task_id, status, raw_status,
                      len(result.image_urls), len(result.video_urls))
        return result


def _err(parse_fn, resp: requests.Response | None = None,
         last_error: Exception | None = None):
    err = f"HTTP {resp.status_code}: {resp.text}" if resp else str(last_error)
    name = parse_fn.__name__
    logger.error("provider.request state=failed parser=%s http_status=%s error_type=%s",
                 name, resp.status_code if resp is not None else "-",
                 type(last_error).__name__ if last_error else "-")
    if "chat" in name:
        return LLMResponse(content="", usage=TokenUsage(),
                            model="", success=False, error=err)
    return AsyncTask(success=False, error=err)
