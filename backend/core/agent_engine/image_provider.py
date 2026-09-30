from __future__ import annotations

from core.observability import log_operation

import time
import logging

import requests

from .models import ImageConfig, ImageResponse

logger = logging.getLogger(__name__)


class ImageProvider:
    """OpenAI-compatible image generation client.

    Supports DALL-E 3 and any provider that follows the
    POST /images/generations endpoint format.
    """

    def __init__(self, config: ImageConfig) -> None:
        self._config = config

    @log_operation
    def generate(self, prompt: str, **kwargs) -> ImageResponse:
        """Generate an image from a text prompt.

        Args:
            prompt: Text description of the desired image.
            **kwargs: Override size, quality, model per request.

        Returns:
            ImageResponse with url or base64 on success.
        """
        url = f"{self._config.base_url.rstrip('/')}/images/generations"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": kwargs.get("model", self._config.model),
            "prompt": prompt,
            "n": 1,
            "size": kwargs.get("size", self._config.size),
            "quality": kwargs.get("quality", self._config.quality),
            "response_format": "url",
        }

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                resp = requests.post(
                    url, json=body, headers=headers,
                    timeout=self._config.timeout,
                )
                if not resp.ok:
                    logger.error("image.generate state=rejected http_status=%s", resp.status_code)
                    return ImageResponse(
                        success=False,
                        error=f"HTTP {resp.status_code}: {resp.text[:300]}",
                    )
                return self._parse_response(resp.json())
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                logger.warning("image.generate state=%s attempt=%s max_attempts=%s error_type=%s",
                               "retrying" if attempt < self._config.max_retries else "failed",
                               attempt + 1, self._config.max_retries + 1, type(exc).__name__,
                               exc_info=True)
                if attempt < self._config.max_retries:
                    time.sleep(attempt + 1)

        return ImageResponse(
            success=False,
            error=str(last_error),
        )

    def _parse_response(self, data: dict) -> ImageResponse:
        try:
            image_data = data["data"][0]
            return ImageResponse(
                url=image_data.get("url"),
                base64=image_data.get("b64_json"),
                revised_prompt=image_data.get("revised_prompt"),
            )
        except (KeyError, IndexError, TypeError) as exc:
            logger.exception("image.generate state=invalid_response")
            return ImageResponse(
                success=False,
                error=f"Failed to parse image response: {exc}",
            )
