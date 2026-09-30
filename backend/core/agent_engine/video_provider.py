from __future__ import annotations

from core.observability import log_operation

import time
import logging

import requests

from .models import VideoConfig, VideoTask, VideoTaskStatus

logger = logging.getLogger(__name__)


class VideoProvider:
    """Base video generation client with async submit/poll pattern.

    Subclass and override `_parse_submit_response` and `_parse_check_response`
    for different video generation APIs (Kling, CogVideoX, Runway, etc.).

    Expected API flow:
      1. POST /videos/generations → {task_id}
      2. GET  /videos/generations/{task_id} → {status, video_url}
    """

    def __init__(self, config: VideoConfig) -> None:
        self._config = config

    @log_operation
    def submit(self, prompt: str, **kwargs) -> VideoTask:
        """Submit a video generation task.

        Args:
            prompt: Text description of the desired video.
            **kwargs: Override model or pass extra params per request.

        Returns:
            VideoTask with task_id and status=pending.
        """
        url = f"{self._config.base_url.rstrip('/')}/videos/generations"
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": kwargs.get("model", self._config.model),
            "prompt": prompt,
        }
        body.update(kwargs)

        try:
            resp = requests.post(
                url, json=body, headers=headers,
                timeout=self._config.timeout,
            )
            if not resp.ok:
                logger.error("video.submit state=rejected http_status=%s", resp.status_code)
                return VideoTask(
                    task_id="",
                    status=VideoTaskStatus.FAILED,
                    error=f"HTTP {resp.status_code}: {resp.text[:300]}",
                )
            return self._parse_submit_response(resp.json())
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.exception("video.submit state=failed")
            return VideoTask(
                task_id="",
                status=VideoTaskStatus.FAILED,
                error=str(exc),
            )

    def check(self, task_id: str) -> VideoTask:
        """Check the status of a video generation task.

        Args:
            task_id: The task ID returned by submit().

        Returns:
            VideoTask with updated status. If completed, url will be set.
        """
        url = f"{self._config.base_url.rstrip('/')}/videos/generations/{task_id}"
        headers = {"Authorization": f"Bearer {self._config.api_key}"}

        try:
            resp = requests.get(url, headers=headers, timeout=self._config.timeout)
            if not resp.ok:
                logger.error("video.poll state=rejected http_status=%s", resp.status_code)
                return VideoTask(
                    task_id=task_id,
                    status=VideoTaskStatus.FAILED,
                    error=f"HTTP {resp.status_code}: {resp.text[:300]}",
                )
            return self._parse_check_response(resp.json(), task_id)
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.exception("video.poll state=failed")
            return VideoTask(
                task_id=task_id,
                status=VideoTaskStatus.FAILED,
                error=str(exc),
            )

    @log_operation
    def wait_until_done(self, task_id: str, max_wait: float = 600) -> VideoTask:
        """Poll a video task until it completes or fails.

        Blocks the calling thread (intended for use inside QThread workers).

        Args:
            task_id: The task ID returned by submit().
            max_wait: Maximum seconds to wait before giving up.

        Returns:
            Final VideoTask state.
        """
        deadline = time.time() + max_wait
        previous_status = None
        while time.time() < deadline:
            task = self.check(task_id)
            if task.status != previous_status:
                logger.log(logging.ERROR if task.status == VideoTaskStatus.FAILED else logging.INFO,
                           "video.poll state=%s", task.status)
                previous_status = task.status
            if task.status in (VideoTaskStatus.COMPLETED, VideoTaskStatus.FAILED):
                return task
            time.sleep(self._config.poll_interval)
        logger.error("video.poll state=timed_out max_wait_seconds=%s", max_wait)
        return VideoTask(
            task_id=task_id,
            status=VideoTaskStatus.FAILED,
            error=f"Timed out after {max_wait}s",
        )

    def _parse_submit_response(self, data: dict) -> VideoTask:
        """Parse the submit API response. Override for custom formats."""
        task_id = data.get("id") or data.get("task_id") or data.get("request_id", "")
        if not task_id:
            logger.error("video.submit state=invalid_response reason=missing_task_id")
            return VideoTask(
                task_id="",
                status=VideoTaskStatus.FAILED,
                error=f"No task_id in response: {data}",
            )
        return VideoTask(task_id=task_id, status=VideoTaskStatus.PENDING)

    def _parse_check_response(self, data: dict, task_id: str) -> VideoTask:
        """Parse the check API response. Override for custom formats."""
        raw_status = data.get("status", "").lower()
        status_map = {
            "pending": VideoTaskStatus.PENDING,
            "processing": VideoTaskStatus.PROCESSING,
            "running": VideoTaskStatus.PROCESSING,
            "completed": VideoTaskStatus.COMPLETED,
            "success": VideoTaskStatus.COMPLETED,
            "succeeded": VideoTaskStatus.COMPLETED,
            "failed": VideoTaskStatus.FAILED,
            "error": VideoTaskStatus.FAILED,
        }
        status = status_map.get(raw_status, VideoTaskStatus.PENDING)

        # Try common response shapes for video URL
        video_url = (
            data.get("video_url")
            or data.get("output", {}).get("video_url")
            or data.get("result", {}).get("video_url")
            or data.get("content", {}).get("video_url")
        )
        cover_url = (
            data.get("cover_url")
            or data.get("output", {}).get("cover_url")
            or data.get("result", {}).get("cover_url")
        )
        error = data.get("error") or data.get("message")

        return VideoTask(
            task_id=task_id,
            status=status,
            url=video_url,
            cover_url=cover_url,
            error=error if status == VideoTaskStatus.FAILED else None,
        )
