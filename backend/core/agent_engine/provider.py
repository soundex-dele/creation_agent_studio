from __future__ import annotations

import json
import logging
import time

import requests

from .models import EngineConfig, LLMResponse, TokenUsage
from core.observability import log_operation

logger = logging.getLogger(__name__)


class LLMProvider:
    """OpenAI-compatible API client."""

    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._total_usage = TokenUsage()

    @log_operation
    def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Send a chat completion request and return the parsed response."""
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._config.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self._config.temperature),
            "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
        }

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                resp = requests.post(
                    url, json=body, headers=headers,
                    timeout=self._config.timeout,
                )
                if not resp.ok:
                    logger.error("llm.complete state=rejected http_status=%s", resp.status_code)
                    return LLMResponse(
                        content="",
                        usage=TokenUsage(),
                        model=self._config.model,
                        success=False,
                        error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )
                return self._parse_response(resp.json())
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                logger.warning("llm.complete state=connection_failed attempt=%s max_attempts=%s",
                               attempt + 1, self._config.max_retries + 1, exc_info=True)
                if attempt < self._config.max_retries:
                    time.sleep(attempt + 1)

        return LLMResponse(
            content="",
            usage=TokenUsage(),
            model=self._config.model,
            success=False,
            error=str(last_error),
        )

    def complete_stream(self, messages: list[dict], **kwargs):
        """Stream a chat completion, yielding content deltas.

        Raises ``RuntimeError`` on a non-2xx HTTP response, on a provider
        error object in the stream, or if the connection cannot be established
        after ``max_retries`` attempts. (The concrete type is a deliberate
        simplification over the ``requests.HTTPError`` that ``raise_for_status``
        would raise; callers catch broadly.)

        Streaming is NOT retried mid-stream — a partially consumed stream
        cannot be safely resumed. Connection/timeout failures while establishing
        the request are retried up to ``max_retries`` times. The underlying
        response is closed when the generator exits.
        """
        started = time.perf_counter()
        logger.info("llm.stream state=started messages=%s", len(messages))
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._config.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self._config.temperature),
            "max_tokens": kwargs.get("max_tokens", self._config.max_tokens),
            "stream": True,
        }

        last_error: Exception | None = None
        resp = None
        # Retry only connection establishment; a non-2xx HTTP status raises
        # immediately (not caught below) so auth/server errors aren't masked.
        for attempt in range(self._config.max_retries + 1):
            try:
                resp = requests.post(
                    url, json=body, headers=headers,
                    timeout=self._config.timeout, stream=True,
                )
                if not resp.ok:
                    logger.error("llm.stream state=rejected http_status=%s", resp.status_code)
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                resp = None
                logger.warning("llm.stream state=connection_failed attempt=%s max_attempts=%s",
                               attempt + 1, self._config.max_retries + 1, exc_info=True)
                if attempt < self._config.max_retries:
                    time.sleep(attempt + 1)
        if resp is None:
            logger.error("llm.stream state=retry_exhausted")
            raise RuntimeError(str(last_error))

        try:
            for line in resp.iter_lines():
                if not line:
                    continue
                text = line.decode("utf-8") if isinstance(line, bytes) else line
                if not text.startswith("data: "):
                    continue
                payload = text[len("data: "):].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                    if isinstance(data, dict) and "error" in data:
                        raise RuntimeError(f"Stream error: {data['error']}")
                    delta = data["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
            logger.info("llm.stream state=completed duration_ms=%.1f",
                        (time.perf_counter() - started) * 1000)
        except Exception:
            logger.exception("llm.stream state=failed")
            raise
        finally:
            resp.close()
            logger.info("llm.stream state=closed duration_ms=%.1f",
                        (time.perf_counter() - started) * 1000)

    def _parse_response(self, data: dict) -> LLMResponse:
        try:
            content = data["choices"][0]["message"]["content"]
            raw_usage = data.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=raw_usage.get("prompt_tokens", 0),
                completion_tokens=raw_usage.get("completion_tokens", 0),
                total_tokens=raw_usage.get("total_tokens", 0),
            )
            model = data.get("model", self._config.model)
            self._total_usage = self._total_usage + usage
            return LLMResponse(content=content, usage=usage, model=model)
        except (KeyError, IndexError, TypeError) as exc:
            logger.exception("llm.complete state=invalid_response")
            return LLMResponse(
                content="",
                usage=TokenUsage(),
                model=self._config.model,
                success=False,
                error=f"Failed to parse API response: {exc}",
            )

    @property
    def total_usage(self) -> TokenUsage:
        return self._total_usage
