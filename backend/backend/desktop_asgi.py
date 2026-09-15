"""ASGI entrypoint that serves the bundled React SPA and the Django API."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from backend.asgi import application as django_application


FRONTEND_ROOT = Path(os.environ["CREATION_STUDIO_FRONTEND_DIST"]).resolve()
DJANGO_PREFIXES = (
    "/api/",
    "/admin/",
    "/healthz/",
    "/readyz/",
    "/static/",
    "/media/",
    "/swagger/",
    "/redoc/",
    "/swagger.json",
)


async def _serve_file(scope, send, path: Path) -> None:
    body = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = [
        (b"content-type", content_type.encode("ascii")),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"x-content-type-options", b"nosniff"),
    ]
    if path.name == "index.html":
        headers.append((b"cache-control", b"no-cache"))
    else:
        headers.append((b"cache-control", b"public, max-age=31536000, immutable"))
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({
        "type": "http.response.body",
        "body": b"" if scope["method"] == "HEAD" else body,
    })


async def application(scope, receive, send):
    if scope["type"] != "http":
        await django_application(scope, receive, send)
        return

    request_path = scope.get("path", "/")
    if scope.get("method") not in {"GET", "HEAD"} or request_path.startswith(DJANGO_PREFIXES):
        await django_application(scope, receive, send)
        return

    relative = request_path.lstrip("/")
    candidate = (FRONTEND_ROOT / relative).resolve() if relative else FRONTEND_ROOT / "index.html"
    if FRONTEND_ROOT not in candidate.parents and candidate != FRONTEND_ROOT:
        candidate = FRONTEND_ROOT / "index.html"
    if not candidate.is_file():
        candidate = FRONTEND_ROOT / "index.html"
    await _serve_file(scope, send, candidate)
