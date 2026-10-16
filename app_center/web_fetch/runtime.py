"""Bounded browser process, supervised by the platform's durable media worker."""
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from modules.platform_api.execution import get_run
from modules.platform_api.tenancy import tenant_database_context
from .backend.access import application_for
from .backend.serializers import FetchSerializer

ENGINE = Path(__file__).with_name("engine")
TASK_TIMEOUT = 90
MAX_OUTPUT = 16 * 1024 * 1024
MESSAGES = {
    "UNSAFE_URL": "目标网址或跳转地址不是允许的公网地址。",
    "ARTICLE_UNAVAILABLE": "文章已删除、已失效或暂时无法查看。",
    "INTERACTION_REQUIRED": "该页面需要登录、验证或受到访问限制，暂不支持抓取。",
    "DOM_TOO_LARGE": "页面内容超过 5 MiB，无法抓取。",
    "EMPTY_CONTENT": "未找到可提取的正文，请检查网址是否为文章页面。",
    "HTTP_ERROR": "来源网站返回错误，页面可能不存在或暂时不可用。",
    "RESOURCE_LIMIT": "页面请求数量或传输大小超出限制。",
    "TIMEOUT": "网页抓取超时，请稍后重试。",
    "BROWSER_UNAVAILABLE": "抓取浏览器不可用，请按应用说明安装 Playwright Chromium。",
    "FETCH_FAILED": "网页抓取失败，请检查来源网站和执行主机网络后重试。",
}


def stop_process(process):
    """Terminate the entire browser tree, not just the Node parent."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_engine(url, sink):
    node = shutil.which("node")
    if not node or not (ENGINE / "node_modules" / "playwright" / "package.json").is_file():
        raise RuntimeError("网页爬取引擎未安装：需要 Node.js 22.12+，在 app_center/web_fetch/engine 执行 npm ci 并安装 Chromium。")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen([node, str(ENGINE / "runner.mjs")], cwd=ENGINE,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        **options)
    events = queue.Queue()

    def read_output():
        try:
            while True:
                line = process.stdout.readline(MAX_OUTPUT + 1)
                if not line:
                    break
                if len(line) > MAX_OUTPUT:
                    events.put({"type": "error", "code": "RESOURCE_LIMIT"})
                    break
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.put(event)
                except (ValueError, UnicodeError):
                    events.put({"type": "error", "code": "FETCH_FAILED"})
                    break
        finally:
            events.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    deadline = time.monotonic() + TASK_TIMEOUT
    result = None
    try:
        process.stdin.write(json.dumps({"url": url}).encode("utf-8"))
        process.stdin.close()
        reader.start()
        while True:
            if sink.cancelled:
                return None
            if time.monotonic() >= deadline:
                raise RuntimeError(MESSAGES["TIMEOUT"])
            try:
                event = events.get(timeout=0.15)
            except queue.Empty:
                continue
            if event is None:
                break
            if event.get("type") == "progress" and event.get("stage") in {"starting", "loading", "rendering", "extracting"}:
                sink.emit("progress.updated", {"stage": event["stage"]})
            elif event.get("type") == "error":
                raise RuntimeError(MESSAGES.get(event.get("code"), MESSAGES["FETCH_FAILED"]))
            elif event.get("type") == "result":
                result = event.get("document")
        # EOF can precede browser cleanup. Keep cancellation and the deadline
        # responsive while waiting for the Node process to exit as well.
        while process.poll() is None:
            if sink.cancelled:
                return None
            if time.monotonic() >= deadline:
                raise RuntimeError(MESSAGES["TIMEOUT"])
            time.sleep(0.1)
        if process.returncode != 0 or not isinstance(result, dict) or not result.get("markdown"):
            raise RuntimeError(MESSAGES["FETCH_FAILED"])
        return result
    except subprocess.TimeoutExpired:
        raise RuntimeError(MESSAGES["TIMEOUT"]) from None
    except (BrokenPipeError, OSError):
        raise RuntimeError(MESSAGES["FETCH_FAILED"]) from None
    finally:
        stop_process(process)
        if reader.ident:
            reader.join(timeout=2)
        process.stdout.close()
        if not process.stdin.closed:
            process.stdin.close()


def execute(payload, sink):
    if sink.cancelled:
        return {}
    # Re-check permissions at execution time; generic run submission cannot
    # bypass the application URL validation or ownership rules.
    with tenant_database_context(payload["organization_id"]):
        run = get_run(payload["run_id"], payload["organization_id"])
        application_for(run.owner, run.organization_id, run.source_id)
        serializer = FetchSerializer(data=payload["input"])
        serializer.is_valid(raise_exception=True)
        url = serializer.validated_data["url"]
    document = run_engine(url, sink)
    if sink.cancelled or document is None:
        return {}
    sink.emit("progress.updated", {"stage": "saving"})
    sink.create_artifact(kind="web-markdown", filename="article.md", content=document["markdown"],
                         mime_type="text/markdown", metadata={"title": document.get("title")})
    sink.create_artifact(kind="web-document", filename="article.json",
                         content=json.dumps(document, ensure_ascii=False, indent=2), mime_type="application/json")
    return {key: document.get(key) for key in ["title", "url", "adapter", "extractionMethod", "capturedAt", "warnings"]}
