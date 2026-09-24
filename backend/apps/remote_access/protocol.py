"""Version 1 allowlist, shared by the relay, connector and local authentication."""
import re
from urllib.parse import parse_qsl, urlsplit

VERSION = 1
MAX_BODY = 1024 * 1024
MAX_CHUNK = 32768
MAX_INFLIGHT = 32
HEARTBEAT = 20
OFFLINE_AFTER = 60
UUID = r"[0-9a-fA-F-]{36}"
TERMINAL_ROOT = "/api/v1/remote-access/terminals/"
TERMINAL_ID = r"[0-9a-f]{32}"
READ_PATHS = (
    rf"{TERMINAL_ROOT}(?:{TERMINAL_ID}/stream/)?",
    r"/api/v1/remote-access/context/",
    r"/api/v1/conversations/(?:[0-9]+/|composer-options/)?",
    r"/api/v1/agents/(?:[0-9]+/)?",
    r"/api/v1/apps/(?:[0-9]+/)?",
    rf"/api/v1/(?:organizations/{UUID}/)?runs/{UUID}(?:/(?:events|stream|snapshot|children))?",
)
WRITE_PATHS = (
    rf"{TERMINAL_ROOT}(?:{TERMINAL_ID}/(?:input|resize|close)/)?",
    r"/api/v1/conversations/",
    r"/api/v1/conversations/[0-9]+/send_message/",
    rf"/api/v1/(?:organizations/{UUID}/)?runs/{UUID}/commands",
)
QUERY_KEYS = {"after", "limit", "page", "page_size", "search", "kind", "application_id", "agent_id", "ordering"}


def validate_request(method, target, body=None, organization_id=None):
    if not isinstance(target, str) or len(target) > 2048 or any(c in target for c in ("\\", "\r", "\n", "#")):
        raise ValueError("Invalid remote path")
    parsed = urlsplit(target)
    patterns = READ_PATHS if method == "GET" else WRITE_PATHS if method == "POST" else ()
    if parsed.scheme or parsed.netloc or '%' in parsed.path or not any(re.fullmatch(p, parsed.path) for p in patterns):
        raise ValueError("Remote endpoint is not allowed")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if any(k not in QUERY_KEYS for k, _ in query) or len(query) != len({k for k, _ in query}):
        raise ValueError("Remote query is not allowed")
    if organization_id and "/organizations/" in parsed.path:
        if parsed.path.split("/organizations/", 1)[1].split("/", 1)[0] != str(organization_id):
            raise ValueError("Organization does not match this computer's authorization")
    if parsed.path.startswith(TERMINAL_ROOT):
        validate_terminal_request(method, parsed.path, query, body)
        return parsed.path
    if method == "POST":
        if not isinstance(body, dict):
            raise ValueError("A JSON object is required")
        if parsed.path.endswith("/commands"):
            if body.get("type") not in {"cancel", "answer", "grant_permission", "deny_permission"}:
                raise ValueError("Remote command is not allowed")
            allowed = {"type", "idempotency_key", "input_request_id", "payload"}
        elif parsed.path.endswith("/send_message/"):
            allowed = {"content", "agent_id", "skill_names", "permission_mode", "collaboration_mode"}
        else:
            allowed = {"title", "agent_id", "application_id", "skill_ids"}
        if set(body) - allowed:
            raise ValueError("Remote request fields are not allowed")
    return parsed.path


def validate_terminal_request(method, path, query, body):
    if query and (not path.endswith('/stream/') or any(k != 'after' or not v.isdecimal()
                                                                      or len(v) > 16 for k, v in query)):
        raise ValueError('Invalid terminal cursor')
    if method == 'GET':
        return
    if not isinstance(body, dict):
        raise ValueError('A JSON object is required')
    action = path[len(TERMINAL_ROOT):].strip('/').split('/')[-1]
    fields = {'input': {'client_id', 'sequence', 'data'}, 'resize': {'cols', 'rows'}, 'close': set()}
    if set(body) != fields.get(action, {'cols', 'rows'}):
        raise ValueError('Invalid terminal fields')
    if action == 'input':
        if (not isinstance(body['client_id'], str) or not re.fullmatch(TERMINAL_ID, body['client_id'])
                or type(body['sequence']) is not int or not 1 <= body['sequence'] <= 2**53 - 1
                or not isinstance(body['data'], str) or not 0 < len(body['data'].encode('utf-8')) <= 16384):
            raise ValueError('Invalid terminal input')
    elif action != 'close':
        if any(type(body[k]) is not int or not 2 <= body[k] <= 500 for k in ('cols', 'rows')):
            raise ValueError('Invalid terminal dimensions')
