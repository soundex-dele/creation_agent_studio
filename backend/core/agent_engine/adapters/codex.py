"""Codex adapter backed by ``codex app-server`` or the optional Python SDK."""
from __future__ import annotations

import importlib
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

from django.conf import settings

from ..messages import format_messages_for_query
from ..models import LLMResponse, TokenUsage
from .base import AgentAdapter

logger = logging.getLogger(__name__)


class _ProtocolObject:
    """Expose app-server's camelCase JSON fields as Python attributes."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __getattr__(self, name):
        camel_name = name.split("_")[0] + "".join(
            part.title() for part in name.split("_")[1:]
        )
        for candidate in (name, camel_name):
            if candidate in self._payload:
                return _protocol_value(self._payload[candidate])
        raise AttributeError(name)

    def model_dump(self, **_options) -> dict:
        return self._payload


def _protocol_value(value):
    if isinstance(value, dict):
        return _ProtocolObject(value)
    if isinstance(value, list):
        return [_protocol_value(item) for item in value]
    return value


class _AppServerTransport:
    """Minimal JSONL client for a dedicated Codex app-server process."""

    def __init__(self, *, codex_bin: Path, approval_decision: str = "") -> None:
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            [str(codex_bin), "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
        self._request_id = 0
        self._request_lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self._notifications: queue.Queue = queue.Queue()
        self._stderr_lines: list[str] = []
        self._approval_decision = approval_decision
        self.input_request: dict | None = None
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr_reader.start()
        try:
            self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "creation_agent_studio",
                        "title": "Creation Agent Studio",
                        "version": "1.0.0",
                    },
                    "capabilities": None,
                },
            )
            self.notify("initialized")
        except Exception:
            self.close()
            raise

    def _read_stdout(self) -> None:
        try:
            assert self._process.stdout is not None
            for raw_line in self._process.stdout:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    message = json.loads(raw_line)
                except json.JSONDecodeError:
                    logger.warning("Ignoring invalid Codex app-server output: %s", raw_line)
                    continue
                request_id = message.get("id")
                if request_id is not None and "method" not in message:
                    pending = self._pending.get(request_id)
                    if pending is not None:
                        pending.put(message)
                    continue
                if request_id is not None:
                    self._handle_server_request(message)
                    continue
                if message.get("method"):
                    self._notifications.put(message)
        finally:
            detail = self._stderr_detail()
            failure = RuntimeError(
                "Codex app-server closed unexpectedly"
                + (f": {detail}" if detail else "")
            )
            for pending in list(self._pending.values()):
                pending.put(failure)
            self._notifications.put(failure)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            line = line.strip()
            if line:
                self._stderr_lines.append(line)
                del self._stderr_lines[:-20]

    def _stderr_detail(self) -> str:
        return " | ".join(self._stderr_lines[-3:])

    def _send(self, message: dict) -> None:
        if self._process.poll() is not None:
            detail = self._stderr_detail()
            raise RuntimeError(
                "Codex app-server is not running" + (f": {detail}" if detail else "")
            )
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._process.stdin.flush()

    def request(self, method: str, params: Optional[dict] = None) -> dict:
        with self._request_lock:
            self._request_id += 1
            request_id = self._request_id
            response_queue: queue.Queue = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
            try:
                self._send({"id": request_id, "method": method, "params": params})
                timeout = float(getattr(settings, "CODEX_REQUEST_TIMEOUT_SECONDS", 30))
                try:
                    response = response_queue.get(timeout=timeout)
                except queue.Empty as exc:
                    raise RuntimeError(
                        f"Codex app-server request timed out: {method}"
                    ) from exc
            finally:
                self._pending.pop(request_id, None)
        if isinstance(response, Exception):
            raise response
        if response.get("error"):
            error = response["error"]
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise RuntimeError(f"Codex app-server {method} failed: {message}")
        return response.get("result") or {}

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        message = {"method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def _handle_server_request(self, message: dict) -> None:
        """Resolve or project an approval into the durable Run input protocol."""
        method = message.get("method", "")
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        }:
            approval_decision = self._approval_decision
            self._approval_decision = ""
            if approval_decision == "grant":
                decision = "accept"
            else:
                decision = "decline"
                if approval_decision != "deny":
                    params = message.get("params") or {}
                    self.input_request = {
                        "input_kind": "permission",
                        "kind": "permission",
                        "header": "Codex 权限确认",
                        "question": str(
                            params.get("reason")
                            or params.get("command")
                            or "Codex 请求执行受保护的操作"
                        ),
                        "options": [
                            {"label": "允许", "value": "grant"},
                            {"label": "拒绝", "value": "deny"},
                        ],
                        "permission": {"method": method, "request": params},
                    }
            self._send({"id": message["id"], "result": {"decision": decision}})
            return
        self._send(
            {
                "id": message["id"],
                "error": {
                    "code": -32601,
                    "message": f"Unsupported app-server request: {method}",
                },
            }
        )

    def next_notification(self, timeout: Optional[float] = None) -> dict:
        message = self._notifications.get(timeout=timeout)
        if isinstance(message, Exception):
            raise message
        return message

    def close(self) -> None:
        if self._process.poll() is not None:
            return
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        self._process.terminate()
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)


def _text_input(text: str) -> list[dict]:
    return [{"type": "text", "text": text, "text_elements": []}]


def _approval_settings(approval_mode: str) -> tuple[str, str]:
    if approval_mode == "auto_review":
        return "on-request", "auto_review"
    return "never", "user"


class _AppServerTurn:
    def __init__(self, *, transport: _AppServerTransport, thread_id: str, text: str, model: str):
        self._transport = transport
        self._thread_id = thread_id
        self._text = text
        self._model = model
        self.id = ""

    def _start(self) -> None:
        if self.id:
            return
        params = {"threadId": self._thread_id, "input": _text_input(self._text)}
        if self._model:
            params["model"] = self._model
        result = self._transport.request("turn/start", params)
        self.id = result["turn"]["id"]

    def stream(self):
        self._start()
        while True:
            message = self._transport.next_notification()
            params = message.get("params") or {}
            if params.get("threadId") not in (None, self._thread_id):
                continue
            notification = _ProtocolObject(
                {"method": message["method"], "payload": params}
            )
            yield notification
            if (
                message["method"] == "turn/completed"
                and params.get("turn", {}).get("id") == self.id
            ):
                return

    def steer(self, text: str) -> None:
        self._start()
        self._transport.request(
            "turn/steer",
            {
                "threadId": self._thread_id,
                "expectedTurnId": self.id,
                "input": _text_input(text),
            },
        )

    def interrupt(self) -> None:
        if self.id:
            self._transport.request(
                "turn/interrupt", {"threadId": self._thread_id, "turnId": self.id}
            )


class _AppServerThread:
    def __init__(self, *, transport: _AppServerTransport, thread_id: str) -> None:
        self._transport = transport
        self.id = thread_id

    def turn(self, text: str, *, model: Optional[str] = None) -> _AppServerTurn:
        return _AppServerTurn(
            transport=self._transport,
            thread_id=self.id,
            text=text,
            model=model or "",
        )

    def run(self, text: str, *, model: Optional[str] = None):
        turn = self.turn(text, model=model)
        chunks: list[str] = []
        completed_items: dict[str, str] = {}
        usage = None
        terminal_turn = None
        for notification in turn.stream():
            if notification.method == "item/agentMessage/delta":
                chunks.append(notification.payload.delta or "")
            elif notification.method == "item/completed":
                item = notification.payload.item
                if getattr(item, "type", "") == "agentMessage":
                    completed_items[item.id] = item.text or ""
            elif notification.method == "thread/tokenUsage/updated":
                usage = notification.payload.token_usage
            elif notification.method == "turn/completed":
                terminal_turn = notification.payload.turn
        final_response = "".join(chunks)
        if not final_response and completed_items:
            final_response = list(completed_items.values())[-1]
        terminal_turn = terminal_turn or _ProtocolObject(
            {"status": "failed", "error": {"message": "Missing turn completion"}}
        )
        return _ProtocolObject(
            {
                "status": terminal_turn.status,
                "final_response": final_response,
                "usage": usage.model_dump() if usage is not None else None,
                "error": (
                    terminal_turn.error.model_dump()
                    if getattr(terminal_turn, "error", None) is not None
                    else None
                ),
            }
        )


class _AppServerCodex:
    def __init__(
        self, *, codex_bin: Path, cwd: str = "", approval_decision: str = ""
    ) -> None:
        self._transport = _AppServerTransport(
            codex_bin=codex_bin,
            approval_decision=approval_decision,
        )
        self._cwd = cwd

    @property
    def input_request(self):
        return self._transport.input_request

    def thread_start(
        self,
        *,
        approval_mode: str,
        base_instructions: Optional[str],
        cwd: str,
        model: Optional[str],
        sandbox: str,
    ) -> _AppServerThread:
        approval_policy, approvals_reviewer = _approval_settings(approval_mode)
        params = {
            "cwd": cwd or self._cwd,
            "approvalPolicy": approval_policy,
            "approvalsReviewer": approvals_reviewer,
            "sandbox": sandbox,
            "baseInstructions": base_instructions,
            "model": model,
        }
        params = {
            key: value for key, value in params.items() if value not in (None, "")
        }
        result = self._transport.request("thread/start", params)
        return _AppServerThread(
            transport=self._transport,
            thread_id=result["thread"]["id"],
        )

    def close(self) -> None:
        self._transport.close()


class _AppServerSdk:
    Sandbox = _ProtocolObject(
        {
            "read_only": "read-only",
            "workspace_write": "workspace-write",
            "full_access": "danger-full-access",
        }
    )
    ApprovalMode = _ProtocolObject(
        {"auto_review": "auto_review", "deny_all": "deny_all"}
    )


@lru_cache(maxsize=1)
def load_codex_sdk():
    """Load ``openai_codex`` from the configured local repository checkout."""
    sdk_path = Path(settings.CODEX_SDK_PATH).expanduser().resolve()
    package_path = sdk_path / "openai_codex"
    if not package_path.is_dir():
        raise RuntimeError(
            f"Codex Python SDK not found at {package_path}. "
            "Set CODEX_REPOSITORY_PATH or CODEX_SDK_PATH to the Codex checkout."
        )
    sdk_path_text = str(sdk_path)
    if sdk_path_text not in sys.path:
        sys.path.insert(0, sdk_path_text)
    return importlib.import_module("openai_codex")


def resolve_codex_binary() -> Path:
    """Resolve an explicit, source-built, or installed Codex binary."""
    configured = str(settings.CODEX_BINARY).strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f"Configured CODEX_BINARY does not exist: {path}")
        return path

    root = Path(settings.CODEX_REPOSITORY_PATH).expanduser().resolve()
    binary_name = "codex.exe" if sys.platform == "win32" else "codex"
    for profile in ("release", "debug"):
        candidate = root / "codex-rs" / "target" / profile / binary_name
        if candidate.is_file():
            return candidate

    # The Windows standalone installer keeps versioned binaries outside the
    # conventional PATH locations used by non-interactive service processes.
    # Prefer the real executable over an npm .cmd shim for app-server stdio.
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            install_root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
            candidates = [
                candidate
                for candidate in install_root.glob(f"*/{binary_name}")
                if candidate.is_file()
            ]
            direct_candidate = install_root / binary_name
            if direct_candidate.is_file():
                candidates.append(direct_candidate)
            if candidates:
                return max(candidates, key=lambda candidate: candidate.stat().st_mtime).resolve()

    discovered = shutil.which("codex")
    if discovered:
        return Path(discovered).resolve()

    raise RuntimeError(
        "Codex executable was not found. Install the Codex App or CLI, add "
        "codex to PATH, or set CODEX_BINARY."
    )


def _enum_value(value) -> str:
    return str(getattr(value, "value", value) or "")


def _usage_payload(token_usage) -> dict:
    if token_usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    last = getattr(token_usage, "last", token_usage)
    return {
        "prompt_tokens": int(getattr(last, "input_tokens", 0) or 0),
        "completion_tokens": int(getattr(last, "output_tokens", 0) or 0),
        "total_tokens": int(getattr(last, "total_tokens", 0) or 0),
    }


def _sandbox(sdk):
    configured = settings.CODEX_SANDBOX.strip().lower()
    values = {
        "read-only": sdk.Sandbox.read_only,
        "workspace-write": sdk.Sandbox.workspace_write,
        "danger-full-access": sdk.Sandbox.full_access,
        "full-access": sdk.Sandbox.full_access,
    }
    try:
        return values[configured]
    except KeyError as exc:
        raise ValueError(
            "CODEX_SANDBOX must be read-only, workspace-write, or danger-full-access"
        ) from exc


def _approval_mode(sdk):
    configured = settings.CODEX_APPROVAL_MODE.strip().lower()
    values = {
        "auto_review": sdk.ApprovalMode.auto_review,
        "deny_all": sdk.ApprovalMode.deny_all,
    }
    try:
        return values[configured]
    except KeyError as exc:
        raise ValueError("CODEX_APPROVAL_MODE must be auto_review or deny_all") from exc


class CodexAdapter(AgentAdapter):
    name = "codex"
    content_mode = "delta"

    def __init__(self, *, model=None, **_options) -> None:
        self.model = model or settings.CODEX_MODEL

    def _client(self, *, cwd: str = "", approval_decision: str = ""):
        transport = str(getattr(settings, "CODEX_TRANSPORT", "app-server")).strip().lower()
        if transport == "app-server":
            return _AppServerSdk, _AppServerCodex(
                codex_bin=resolve_codex_binary(),
                cwd=cwd or settings.CODEX_WORKING_DIRECTORY,
                approval_decision=approval_decision,
            )
        if transport != "python-sdk":
            raise ValueError("CODEX_TRANSPORT must be app-server or python-sdk")
        sdk = load_codex_sdk()
        config = sdk.CodexConfig(
            codex_bin=str(resolve_codex_binary()),
            cwd=cwd or settings.CODEX_WORKING_DIRECTORY,
            client_name="creation_agent_studio",
            client_title="Creation Agent Studio",
        )
        return sdk, sdk.Codex(config=config)

    def complete(self, messages: list[dict], **options) -> LLMResponse:
        system_prompt, query = format_messages_for_query(messages)
        cwd = options.get("working_directory", "") or settings.CODEX_WORKING_DIRECTORY
        sdk, client = self._client(
            cwd=cwd,
            approval_decision=str(options.get("approval_decision") or ""),
        )
        input_request = None
        try:
            thread = client.thread_start(
                approval_mode=_approval_mode(sdk),
                base_instructions=system_prompt or None,
                cwd=cwd,
                model=self.model or None,
                sandbox=_sandbox(sdk),
            )
            result = thread.run(query, model=self.model or None)
            input_request = getattr(client, "input_request", None)
        finally:
            client.close()
        usage = _usage_payload(result.usage)
        success = _enum_value(result.status) == "completed"
        return LLMResponse(
            content=result.final_response or "",
            usage=TokenUsage(**usage),
            model=self.model or "codex-default",
            success=success,
            error=(getattr(result.error, "message", None) if result.error else None),
            input_request=input_request,
        )
