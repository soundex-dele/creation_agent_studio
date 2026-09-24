"""Browser-native downloads: scoped cookies and bounded, resumable relay reads."""
import asyncio
import base64
import json
import re
import time
import uuid

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core import signing
from django.http import JsonResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt
from rest_framework import exceptions
from rest_framework.views import APIView

from .broker import Subscription, publish
from .file_protocol import FILE_CHUNK, MAX_FILE_SIZE
from .models import RemoteDevice
from .protocol import FILE_ROOT, MAX_BODY, MAX_CHUNK, validate_request
from .views import require_relay

COOKIE = 'remote_file_download'
COOKIE_SALT = 'remote-file-download-v1'


class RPCError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


def device_for_owner(device_id, owner_id):
    require_relay()
    device = RemoteDevice.objects.select_related('owner').filter(
        pk=device_id, owner_id=owner_id, owner__is_active=True, confirmed=True, revoked_at__isnull=True).first()
    if not device:
        raise RPCError(403, '此账号已不能访问这台电脑。')
    return device


def grant_owner(request, device_id):
    view = APIView()
    drf_request = view.initialize_request(request)
    view.initial(drf_request)
    device = device_for_owner(device_id, drf_request.user.pk)
    return device.owner_id


def cookie_owner(request, device_id, transfer_id):
    try:
        data = signing.loads(request.COOKIES.get(COOKIE, ''), salt=COOKIE_SALT, max_age=3600)
        if data['device'] != str(device_id) or data['transfer'] != transfer_id:
            raise ValueError()
        device = device_for_owner(device_id, data['owner'])
        if data['auth'] != device.owner.get_session_auth_hash():
            raise ValueError()
        from apps.users.authentication import _require_active_license
        _require_active_license()
        return device.owner_id
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise RPCError(403, '下载授权已过期，请从文件页面重新发起下载。') from None


def topic_for_owner(device_id, owner_id):
    device = device_for_owner(device_id, owner_id)
    if not device.online:
        raise RPCError(503, '电脑暂时离线。')
    return f'device:{device.id}:{device.session_id}'


async def file_rpc(device_id, owner_id, method, path, body=None, key=''):
    validate_request(method, path, body)
    topic = await sync_to_async(topic_for_owner, thread_sensitive=True)(device_id, owner_id)
    rid = uuid.uuid4().hex
    subscription = await Subscription('response:' + rid).open()
    try:
        delivered = await publish(topic, {'type': 'request', 'id': rid, 'method': method, 'path': path,
                                          'body': body, 'idempotency_key': key})
        if not delivered:
            raise RPCError(503, '电脑连接已中断。')
        first = await subscription.receive(timeout=15)
        if first.get('type') != 'start':
            raise RPCError(503, '电脑暂时未响应。')
        status = first.get('status')
        if type(status) is not int or not 200 <= status <= 599:
            raise RPCError(502, '电脑响应无效。')
        result = bytearray()
        while True:
            frame = await subscription.receive(timeout=15)
            if frame.get('type') == 'end':
                break
            if frame.get('type') != 'chunk':
                raise RPCError(503, '电脑传输已中断。')
            data = base64.b64decode(frame.get('body', ''), validate=True)
            if len(data) > MAX_CHUNK or len(result) + len(data) > MAX_BODY:
                raise RPCError(502, '电脑响应过大。')
            result.extend(data)
            await publish(topic, {'type': 'ack', 'id': rid})
        value = json.loads(result)
        if not isinstance(value, dict):
            raise RPCError(502, '电脑响应无效。')
        if status >= 400:
            raise RPCError(status, value.get('detail', '文件操作失败。'))
        return value
    except TimeoutError:
        raise RPCError(503, '电脑响应超时。') from None
    except (ValueError, TypeError):
        raise RPCError(502, '电脑响应无效。') from None
    finally:
        await publish(topic, {'type': 'cancel', 'id': rid})
        await subscription.close()


async def retry_rpc(*args, **kwargs):
    deadline = time.monotonic() + 60
    while True:
        try:
            return await asyncio.wait_for(file_rpc(*args, **kwargs), max(.01, deadline - time.monotonic()))
        except (RPCError, TimeoutError) as exc:
            if isinstance(exc, RPCError) and exc.status not in {502, 503, 504}:
                raise
            if time.monotonic() >= deadline:
                raise RPCError(503, '电脑离线超过 60 秒，请在浏览器中重试下载。') from None
            await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))


def content_url(device_id, transfer_id):
    return f'/api/v1/remote/devices/{device_id}/downloads/{transfer_id}/content/'


def error_response(exc):
    status = getattr(exc, 'status', getattr(exc, 'status_code', 400))
    return JsonResponse({'detail': getattr(exc, 'detail', '文件请求无效。')}, status=status)


@csrf_exempt
async def create_download(request, device_id):
    if request.method != 'POST':
        return JsonResponse({'detail': '仅支持 POST。'}, status=405)
    try:
        owner_id = await sync_to_async(grant_owner, thread_sensitive=True)(request, device_id)
        if request.content_type != 'application/json' or len(request.body) > 16384:
            raise RPCError(400, '下载参数无效。')
        body = json.loads(request.body)
        key = request.headers.get('Idempotency-Key', '')
        if not 1 <= len(key) <= 160:
            raise RPCError(400, '缺少操作幂等标识。')
        item = await file_rpc(device_id, owner_id, 'POST', FILE_ROOT + 'downloads/', body, key)
        if not re.fullmatch('[0-9a-f]{32}', str(item.get('id', ''))):
            raise RPCError(502, '电脑响应无效。')
        device = await sync_to_async(device_for_owner, thread_sensitive=True)(device_id, owner_id)
        url = content_url(device_id, item['id'])
        response = JsonResponse({**item, 'download_url': url})
        response.set_cookie(COOKIE, signing.dumps({'owner': owner_id, 'device': str(device_id), 'transfer': item['id'],
                                                  'auth': device.owner.get_session_auth_hash()}, salt=COOKIE_SALT),
                            max_age=3600, httponly=True, samesite='Strict', path=url,
                            secure=getattr(settings, 'JWT_REFRESH_COOKIE_SECURE', not settings.DEBUG))
        response['Cache-Control'] = 'no-store'
        return response
    except (RPCError, exceptions.APIException, ValueError, TypeError) as exc:
        return error_response(exc)


def byte_range(header, size):
    if not header:
        return 0, size - 1, 200
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
    if not match or not any(match.groups()) or size == 0:
        raise RPCError(416, '下载范围无效。')
    a, b = match.groups()
    start = int(a) if a else max(0, size - int(b))
    end = min(int(b), size - 1) if a and b else size - 1
    if not 0 <= start <= end < size:
        raise RPCError(416, '下载范围无效。')
    return start, end, 206


@csrf_exempt
async def download_content(request, device_id, transfer_id):
    if request.method not in {'GET', 'HEAD'}:
        return JsonResponse({'detail': '仅支持 GET 或 HEAD。'}, status=405)
    size = None
    stream_id = uuid.uuid4().hex
    owner_id = None
    opened = False

    async def release():
        if opened:
            try:
                await asyncio.wait_for(file_rpc(device_id, owner_id, 'POST', f'{FILE_ROOT}downloads/{transfer_id}/release/',
                                                {'stream_id': stream_id}, stream_id), 3)
            except (RPCError, TimeoutError, exceptions.APIException):
                pass  # A relay disconnect is covered by the local stream lease expiry.
    try:
        if not re.fullmatch('[0-9a-f]{32}', transfer_id):
            raise RPCError(404, '下载不存在。')
        owner_id = await sync_to_async(cookie_owner, thread_sensitive=True)(request, device_id, transfer_id)
        item = await retry_rpc(device_id, owner_id, 'GET', f'{FILE_ROOT}transfers/{transfer_id}/')
        if item.get('direction') != 'download' or item.get('state') in {'cancelled', 'failed'}:
            raise RPCError(410, '下载已取消或失效。')
        size = item['size']
        if type(size) is not int or not 0 <= size <= MAX_FILE_SIZE:
            raise RPCError(502, '文件大小无效。')
        requested_range = request.headers.get('Range', '')
        if request.headers.get('If-Range') and request.headers['If-Range'] != item['etag']:
            requested_range = ''
        start, end, status = byte_range(requested_range, size)
        await retry_rpc(device_id, owner_id, 'POST', f'{FILE_ROOT}downloads/{transfer_id}/open/',
                        {'stream_id': stream_id}, stream_id)
        opened = True

        async def read(offset, length):
            value = await retry_rpc(device_id, owner_id, 'GET',
                                    f'{FILE_ROOT}downloads/{transfer_id}/read/?offset={offset}&length={max(1, length)}&stream_id={stream_id}')
            data = base64.b64decode(value['data'], validate=True)
            if value.get('offset') != offset or value.get('etag') != item['etag'] or len(data) != length:
                raise RPCError(409, '源文件已变化，请重新下载。')
            return data

        first = await read(start, min(FILE_CHUNK, max(0, end - start + 1)))

        async def stream():
            offset, block = start, first
            try:
                while True:
                    if block:
                        yield block
                    # Confirm only after the ASGI consumer has accepted this bounded block.
                    await retry_rpc(device_id, owner_id, 'POST', f'{FILE_ROOT}downloads/{transfer_id}/progress/',
                                    {'offset': offset, 'length': len(block), 'stream_id': stream_id}, uuid.uuid4().hex)
                    offset += len(block)
                    if offset > end:
                        return
                    block = await read(offset, min(FILE_CHUNK, end - offset + 1))
            finally:
                await release()

        async def empty():
            if False:
                yield b''

        if request.method == 'HEAD':
            await release()

        response = StreamingHttpResponse(stream() if request.method == 'GET' else empty(),
                                         status=status, content_type='application/octet-stream')
        response['Content-Length'] = str(max(0, end - start + 1))
        response['Content-Disposition'] = content_disposition_header(True, ''.join(c for c in item['name'] if ord(c) >= 32))
        response['ETag'] = item['etag']
        response['Accept-Ranges'] = 'bytes'
        response['Cache-Control'] = 'no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Accel-Buffering'] = 'no'
        if status == 206:
            response['Content-Range'] = f'bytes {start}-{end}/{size}'
        return response
    except (RPCError, exceptions.APIException, ValueError, TypeError) as exc:
        await release()
        response = error_response(exc)
        if response.status_code == 416 and size is not None:
            response['Content-Range'] = f'bytes */{size}'
        return response
