"""Isolated DTK source bridge. JSON stdin only; never print exception details."""
import asyncio
from contextlib import contextmanager
import json
import re
from pathlib import Path
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from douyin_video_url import (ADAPTER, NativeSigner, Platform, SigningRequest,
    SigningSession, StaticFingerprint, RequestSpec, WreqTransport, Outcome,
    load_cookies, make_identity, configure, httpx, DtkError, VideoUrlError)
from dtk.platforms.douyin.endpoints import AUTHOR_PROFILE, AUTHOR_POSTS, CONTENT_DETAIL, COMMENTS, COMMENT_REPLIES
from dtk.urls import resolve, identify, ResourceKind
from dtk.transport.base import TransportFailure
from radar_source import HOTLIST, SEARCH, request_spec, parse_hotlist, parse_search, search_failure


class BridgeError(Exception):
    diagnostic = None


def error_result(exc):
    """Keep typed failures across IPC without exception messages or URLs."""
    if isinstance(exc, BridgeError):
        return {"error": str(exc), "diagnostic": exc.diagnostic}
    diagnostic = {"error_type": type(exc).__name__}
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        code = "timeout"
    elif isinstance(exc, TransportFailure):
        code = "timeout" if isinstance(exc.cause, (TimeoutError, httpx.TimeoutException)) else "unavailable"
    elif isinstance(exc, VideoUrlError):
        code = "credentials"
    elif isinstance(exc, DtkError):
        code = {"RATE_LIMITED": "limited", "UNAUTHENTICATED": "auth",
            "UPSTREAM_RISK_CONTROL": "risk_control", "SIGNING_FAILED": "signature",
            "CONTENT_PRIVATE": "content_unavailable", "NOT_FOUND": "content_unavailable"}.get(exc.code.value, "invalid")
    else:
        code = "unavailable"
    return {"error": code, "diagnostic": diagnostic}


@contextmanager
def failure_context(stage, endpoint=None):
    try:
        yield
    except Exception as exc:
        result = error_result(exc)
        error = BridgeError(result["error"])
        error.diagnostic = {"stage": stage, **({"endpoint": endpoint} if endpoint else {}),
            **(result["diagnostic"] or {})}
        raise error from None


async def author_id(url, identity):
    async with httpx.AsyncClient(headers={"User-Agent": identity.fingerprint.user_agent},
            timeout=20, follow_redirects=False, trust_env=False) as client:
        async def redirect(target):
            kind = identify(target)
            if kind.resource is ResourceKind.USER and kind.resource_id:
                return None
            async with client.stream("GET", target) as response:
                if response.status_code >= 400:
                    error = BridgeError("unavailable")
                    error.diagnostic = {"http_status": response.status_code}
                    raise error
                return response.headers.get("location") if 300 <= response.status_code < 400 else None
        kind = await resolve(url, redirect)
    if kind.platform is not Platform.DOUYIN or kind.resource is not ResourceKind.USER or not kind.resource_id:
        raise BridgeError("invalid")
    return kind.resource_id


async def request(endpoint, params, identity, transport=None):
    with failure_context("sign", endpoint):
        spec = (request_spec(endpoint, params, ADAPTER, identity) if endpoint in (HOTLIST, SEARCH)
                else ADAPTER.build_request(endpoint, **params, profile=ADAPTER.profile_for(identity.fingerprint)))
        signed = await NativeSigner(Platform.DOUYIN).sign(
            SigningRequest.get(spec["url"], spec["params"], spec["headers"]),
            StaticFingerprint.of(identity.fingerprint),
            SigningSession(cookies=identity.cookies, identity_id=identity.id))
    own = transport is None
    with failure_context("transport", endpoint):
        transport = transport if transport is not None else WreqTransport()
    response = None
    stage = "response"
    try:
        with failure_context("transport", endpoint):
            response = await transport.request(identity, RequestSpec(url=signed.signed_url(spec["url"]),
                headers={**spec["headers"], **signed.headers}, endpoint=endpoint), timeout=30)
        if response.status == 429:
            raise BridgeError("limited")
        classification = transport.classify(response)
        outcome = classification.outcome
        if outcome is not Outcome.OK:
            if outcome is Outcome.BUSINESS_ERROR:
                raise BridgeError(search_failure(response.json_or_none()) if endpoint == SEARCH else "content_unavailable")
            if classification.rule.startswith("signature."):
                raise BridgeError("signature")
            if classification.rule == "body.challenge_marker":
                raise BridgeError("challenge")
            if classification.rule in ("body.empty", "payload.withheld", "payload.bare_envelope"):
                raise BridgeError("empty_response")
            if response.status == 401:
                raise BridgeError("auth")
            raise BridgeError("risk_control" if outcome is Outcome.RISK_CONTROL else "unavailable")
        stage = "parse"
        payload = response.json_or_none()
        if not isinstance(payload, dict):
            raise BridgeError("invalid")
        now = datetime.now(timezone.utc)
        if endpoint in (HOTLIST, SEARCH):
            if payload.get('status_code') not in (0, '0'):
                raise BridgeError('invalid')
            try:
                return (parse_hotlist if endpoint == HOTLIST else parse_search)(payload, now.isoformat())
            except (ValueError, TypeError, AttributeError):
                raise BridgeError('invalid') from None
        if endpoint == AUTHOR_PROFILE:
            result = ADAPTER.parse_author(payload)
        elif endpoint == AUTHOR_POSTS:
            result = ADAPTER.parse_author_posts(payload, fetched_at=now)
        elif endpoint == COMMENTS:
            result = ADAPTER.parse_comments(payload, content_id=params['aweme_id'])
        elif endpoint == COMMENT_REPLIES:
            result = ADAPTER.parse_comment_replies(payload, content_id=params['item_id'], parent_id=params['comment_id'])
        else:
            result = ADAPTER.parse_content(payload, fetched_at=now)
        return result.model_dump(mode="json")
    except Exception as exc:
        result = error_result(exc)
        error = BridgeError(result["error"])
        error.diagnostic = {"endpoint": endpoint, "stage": stage,
            **({"http_status": response.status} if response is not None else {}),
            **(result["diagnostic"] or {})}
        if endpoint in (HOTLIST, SEARCH) and response is not None:
            envelope = response.json_or_none()
            status = envelope.get('status_code') if isinstance(envelope, dict) else None
            if type(status) is int:
                error.diagnostic['upstream_status'] = status
        raise error from None
    finally:
        if own:
            await transport.close()


async def run(data):
    config = data["config"]
    cookies = load_cookies(config["cookies"])
    if any(not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key) or any(ord(c) < 32 or ord(c) == 127 for c in value) for key, value in cookies.items()):
        raise BridgeError("credentials")
    if "\r" in config["user_agent"] or "\n" in config["user_agent"]:
        raise BridgeError("credentials")
    identity = make_identity(cookies, config["user_agent"],
        config.get("screen", "1920x1080"), config.get("language", "zh-CN"), config.get("timezone", "Asia/Shanghai"))
    operation = data["operation"]
    if operation == "validate":
        return {"valid": True}
    params = data.get("params", {})
    if operation in ('radar_hotlist', 'radar_search'):
        return await request(HOTLIST if operation == 'radar_hotlist' else SEARCH, params, identity)
    if operation == "profile":
        with failure_context("resolve_url", AUTHOR_PROFILE):
            sec_user_id = await author_id(params["url"], identity)
        return await request(AUTHOR_PROFILE, {"sec_user_id": sec_user_id}, identity)
    if operation == "pages":
        return await request(AUTHOR_POSTS, params, identity)
    if operation == "detail":
        return await request(CONTENT_DETAIL, params, identity)
    if operation == "comments":
        return await request(COMMENTS, params, identity)
    if operation == "replies":
        return await request(COMMENT_REPLIES, params, identity)
    raise BridgeError("invalid")


def main():
    configure(level="critical")
    try:
        data = json.load(sys.stdin)
        async def bounded():
            async with asyncio.timeout(50):
                return await run(data)
        result = {"data": asyncio.run(bounded())}
    except Exception as exc:
        result = error_result(exc)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
