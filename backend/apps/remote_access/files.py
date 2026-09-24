"""Bounded connector-owned file transfers. All file I/O runs outside the event loop."""
import asyncio
import base64
import errno
import hashlib
import heapq
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from apps.applications.runtime_paths import filesystem_roots
from .file_protocol import FILE_CHUNK, MAX_FILE_SIZE
from .protocol import FILE_ROOT, validate_request
from .terminals import TerminalError

IDLE_TTL = 24 * 3600
PART_PREFIX = '.agent-studio-upload-'


class FileError(TerminalError):
    pass


def safe_path(raw):
    if not raw or '\x00' in raw:
        raise FileError(400, '请输入绝对路径。')
    if os.name == 'nt':
        normalized = raw.replace('/', '\\')
        if normalized.startswith(('\\\\?\\', '\\\\.\\', '\\??\\')):
            raise FileError(400, '不支持设备路径。')
        tail = os.path.splitdrive(normalized)[1]
        if ':' in tail or any(reserved_name(part) for part in tail.split('\\') if part and part not in {'.', '..'}):
            raise FileError(400, '不支持特殊文件名或备用数据流。')
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise FileError(400, '请输入绝对路径。')
    return path.resolve(strict=True)


def reserved_name(name):
    stem = name.split('.')[0].rstrip(' ').upper()
    return (name.endswith((' ', '.')) or stem in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', 'CLOCK$'}
            or bool(re.fullmatch(r'(?:COM|LPT)[1-9¹²³]', stem)))


def validate_name(name):
    if (not name or name in {'.', '..'} or len(name.encode('utf-8')) > 240
            or any(c in name for c in '/\\\x00') or any(ord(c) < 32 for c in name)
            or (os.name == 'nt' and (any(c in name for c in ':<>"|?*') or reserved_name(name)))):
        raise FileError(400, '文件名无效或过长。')


def regular_file(path):
    if not stat.S_ISREG(os.stat(path).st_mode):
        raise FileError(400, '仅支持传输普通文件。')
    # O_NONBLOCK avoids blocking on a FIFO swapped in between resolution/open.
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
                 | getattr(os, 'O_NOFOLLOW', 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise FileError(400, '仅支持传输普通文件。')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def list_directory(raw, cursor):
    path = safe_path(raw)
    if not path.is_dir():
        raise FileError(400, '这不是目录。')
    after = None
    if cursor:
        try:
            after = json.loads(base64.urlsafe_b64decode(cursor))
            if (not isinstance(after, list) or len(after) != 3 or type(after[0]) is not int
                    or after[0] not in {0, 1} or not all(isinstance(s, str) for s in after[1:])):
                raise ValueError()
            after = tuple(after)
        except (ValueError, TypeError):
            raise FileError(400, '目录分页已失效，请刷新。') from None
    def entries():
        with os.scandir(path) as scan:
            for entry in scan:
                if entry.name.startswith(PART_PREFIX):
                    continue
                try:
                    info = entry.stat()
                    directory = stat.S_ISDIR(info.st_mode)
                    if not directory and not stat.S_ISREG(info.st_mode):
                        continue
                    key = (0 if directory else 1, entry.name.casefold(), entry.name)
                    if after is None or key > after:
                        yield key, {'name': entry.name, 'path': str(path / entry.name),
                                    'directory': directory, 'size': info.st_size if not directory else None,
                                    'modified_at': info.st_mtime}
                except OSError:
                    continue
    page = heapq.nsmallest(101, entries(), key=lambda item: item[0])
    next_cursor = base64.urlsafe_b64encode(json.dumps(page[99][0]).encode()).decode() if len(page) > 100 else ''
    return {'path': str(path), 'parent': str(path.parent) if path.parent != path else '',
            'entries': [entry for _, entry in page[:100]], 'next_cursor': next_cursor}


class FileManager:
    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)
        self.transfers = {}
        self.creations = {}
        self.streams = {}
        self.lock = threading.RLock()
        self.grant = None

    def public(self, item):
        return {key: item[key] for key in ('id', 'direction', 'name', 'size', 'offset', 'state', 'path', 'etag', 'detail')}

    def remove_part(self, record):
        path = Path(record['part'])
        if path.name != f"{PART_PREFIX}{record['id']}.part":
            return
        try:
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and [info.st_dev, info.st_ino] == record['identity']:
                path.unlink()
        except FileNotFoundError:
            pass

    def cleanup(self):
        with self.lock:
            now = time.time()
            for item in list(self.transfers.values()):
                if now - item['touched'] >= IDLE_TTL:
                    self.cancel(item)
                    self.transfers.pop(item['id'], None)
            self.creations = {key: value for key, value in self.creations.items() if value[1] in self.transfers}
            self.state_dir.mkdir(parents=True, exist_ok=True)
            for manifest in self.state_dir.glob('*.json'):
                try:
                    record = json.loads(manifest.read_text(encoding='utf-8'))
                    if record['id'] in self.transfers:
                        continue
                    part = Path(record['part'])
                    if now - (part.lstat().st_mtime if part.exists() else manifest.stat().st_mtime) >= IDLE_TTL:
                        self.remove_part(record)
                        manifest.unlink(missing_ok=True)
                except (OSError, ValueError, KeyError, TypeError):
                    continue

    def cancel(self, item):
        self.streams = {key: stream for key, stream in self.streams.items() if stream['transfer'] != item['id']}
        if item['direction'] == 'upload':
            self.remove_part(item)
            (self.state_dir / (item['id'] + '.json')).unlink(missing_ok=True)
        if item['direction'] == 'download' or item['state'] != 'completed':
            item['state'] = 'cancelled'

    async def close_all(self):
        def close():
            with self.lock:
                for item in self.transfers.values():
                    try:
                        self.cancel(item)
                    except OSError:
                        pass  # The journal retains failed cleanup for the next sweep.
                self.transfers.clear()
                self.creations.clear()
                self.streams.clear()
        await asyncio.to_thread(close)

    def create(self, direction, body, key):
        fingerprint = json.dumps([direction, body], sort_keys=True)
        if key in self.creations:
            previous, tid = self.creations[key]
            if previous != fingerprint:
                raise FileError(409, '同一创建请求的参数不能更改。')
            return self.public(self.transfers[tid])
        if sum(item['direction'] == direction and item['state'] in {'ready', 'transferring'}
               for item in self.transfers.values()) >= 2:
            raise FileError(429, '此电脑已有两个同方向传输，请等待或取消已有任务。')
        if len(self.transfers) >= 1024:
            raise FileError(429, '传输记录已达到上限，请稍后重试。')
        path = safe_path(body['path'])
        tid = uuid.uuid4().hex
        item = dict(id=tid, direction=direction, name='', size=0, offset=0, state='ready', path=str(path),
                    etag='', detail='', touched=time.time(), ranges=[])
        if direction == 'upload':
            validate_name(body['name'])
            if not path.is_dir():
                raise FileError(400, '上传目标不是目录。')
            part = path / f'{PART_PREFIX}{tid}.part'
            fd = os.open(part, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0), 0o600)
            info = os.fstat(fd)
            os.close(fd)
            item.update(name=body['name'], size=body['size'], part=str(part), identity=[info.st_dev, info.st_ino], last=None)
            try:
                self.state_dir.mkdir(parents=True, exist_ok=True)
                with (self.state_dir / (tid + '.json')).open('x', encoding='utf-8') as output:
                    json.dump({'id': tid, 'part': str(part), 'identity': item['identity']}, output)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
        else:
            with regular_file(path) as source:
                info = os.fstat(source.fileno())
            if info.st_size > MAX_FILE_SIZE:
                raise FileError(413, '文件超过 2 GiB 上限。')
            item.update(name=path.name, size=info.st_size, signature=signature(info),
                        etag='"' + hashlib.sha256(repr(signature(info)).encode()).hexdigest() + '"')
        self.transfers[tid] = item
        self.creations[key] = fingerprint, tid
        return self.public(item)

    def upload_chunk(self, item, body):
        try:
            data = base64.b64decode(body['data'], validate=True)
        except ValueError:
            raise FileError(400, '文件分块编码无效。') from None
        digest = hashlib.sha256(data).hexdigest()
        if digest != body['sha256'] or not 0 < len(data) <= FILE_CHUNK:
            raise FileError(400, '文件分块校验失败。')
        if body['offset'] < item['offset']:
            if body['offset'] % FILE_CHUNK or len(data) != min(FILE_CHUNK, item['size'] - body['offset']):
                raise FileError(409, '重复分块边界无效。')
            with regular_file(item['part']) as source:
                info = os.fstat(source.fileno())
                if [info.st_dev, info.st_ino] != item['identity']:
                    raise FileError(409, '上传临时文件已变化。')
                source.seek(body['offset'])
                if source.read(len(data)) != data:
                    raise FileError(409, '重复分块内容不一致。')
            return self.public(item)
        if body['offset'] != item['offset'] or body['offset'] + len(data) > item['size']:
            raise FileError(409, '上传偏移不一致，请查询传输状态后重试。')
        if len(data) != min(FILE_CHUNK, item['size'] - item['offset']):
            raise FileError(400, '文件分块长度无效。')
        fd = os.open(item['part'], os.O_RDWR | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
                     | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'r+b') as output:
            info = os.fstat(output.fileno())
            if [info.st_dev, info.st_ino] != item['identity'] or not stat.S_ISREG(info.st_mode):
                raise FileError(409, '上传临时文件已变化。')
            output.seek(item['offset'])
            output.write(data)
            output.flush()
        item['last'] = body['offset'], len(data), digest
        item['offset'] += len(data)
        item['state'] = 'transferring'
        return self.public(item)

    def complete(self, item):
        if item['state'] == 'completed':
            return self.public(item)
        if item['offset'] != item['size']:
            raise FileError(409, '文件尚未上传完整。')
        part = Path(item['part'])
        info = part.lstat()
        if ([info.st_dev, info.st_ino] != item['identity'] or not stat.S_ISREG(info.st_mode)
                or info.st_size != item['size']):
            raise FileError(409, '上传临时文件已变化。')
        with part.open('r+b') as source:
            os.fsync(source.fileno())
        original = Path(item['name'])
        for index in range(10000):
            name = original.name if not index else f'{original.stem} ({index}){original.suffix}'
            destination = part.parent / name
            try:
                if os.name == 'nt':
                    os.rename(part, destination)  # Windows rename never replaces an existing destination.
                else:
                    os.link(part, destination, follow_symlinks=False)
                item.update(name=name, path=str(destination), state='completed')
                try:
                    if os.name != 'nt':
                        part.unlink()
                    (self.state_dir / (item['id'] + '.json')).unlink(missing_ok=True)
                except OSError:
                    pass  # Publication succeeded. Retry cleanup from the retained journal, not publication.
                return self.public(item)
            except FileExistsError:
                continue
        raise FileError(409, '同名文件过多，请更换目录或文件名。')

    def open_stream(self, item, stream_id):
        # A crashed relay cannot retain a slot forever; slow readers reacquire before reading.
        now = time.monotonic()
        self.streams = {key: value for key, value in self.streams.items() if now - value['touched'] < 90}
        existing = self.streams.get(stream_id)
        if existing and existing['transfer'] != item['id']:
            raise FileError(409, '下载流与任务不匹配。')
        if not existing and len(self.streams) >= 2:
            raise FileError(429, '此电脑已有两个活动下载流，请稍后重试。')
        self.streams[stream_id] = {'transfer': item['id'], 'touched': now}
        return {'stream_id': stream_id}

    def read_chunk(self, item, offset, length):
        try:
            return self.read_file(item, offset, length)
        except OSError as exc:
            status = 404 if isinstance(exc, FileNotFoundError) else 403 if isinstance(exc, PermissionError) else 409
            detail = '源文件已不存在。' if status == 404 else '本机服务账号已无法读取源文件，请检查文件和权限。'
            item.update(state='failed', detail=detail)
            raise FileError(status, detail) from None
        except FileError as exc:
            if exc.status != 416:
                item.update(state='failed', detail=exc.detail)
            raise

    def read_file(self, item, offset, length):
        with regular_file(Path(item['path'])) as source:
            if signature(os.fstat(source.fileno())) != item['signature']:
                item.update(state='failed', detail='源文件已变化，请重新下载。')
                raise FileError(409, item['detail'])
            if offset > item['size']:
                raise FileError(416, '下载范围无效。')
            source.seek(offset)
            data = source.read(min(length, item['size'] - offset))
            if signature(os.fstat(source.fileno())) != item['signature']:
                item.update(state='failed', detail='读取过程中源文件已变化。')
                raise FileError(409, item['detail'])
        return {'data': base64.b64encode(data).decode(), 'offset': offset, 'etag': item['etag']}

    def progress(self, item, offset, length):
        if offset + length > item['size']:
            raise FileError(400, '下载进度无效。')
        merged = []
        for start, end in sorted([*item['ranges'], (offset, offset + length)]):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        if len(merged) > 1024:
            raise FileError(429, '下载分段过多，请重新创建任务。')
        item['ranges'] = merged
        item['offset'] = sum(end - start for start, end in merged)
        item['state'] = 'completed' if item['offset'] == item['size'] else 'transferring'
        return self.public(item)

    def execute(self, method, target, body, key):
        path = validate_request(method, target, body)
        if method == 'POST' and (not isinstance(key, str) or not 1 <= len(key) <= 160):
            raise FileError(400, '缺少操作幂等标识。')
        suffix = path[len(FILE_ROOT):].strip('/').split('/')
        if suffix == ['roots']:
            return {'roots': [{'name': str(root), 'path': str(root)} for root in filesystem_roots()], 'home': str(Path.home())}
        if suffix == ['list']:
            return list_directory(body['path'], body['cursor'])
        with self.lock:
            if suffix == ['transfers']:
                return {'transfers': [self.public(item) for item in self.transfers.values()
                                      if item['state'] in {'ready', 'transferring'}]}
            if suffix in (['uploads'], ['downloads']):
                return self.create('upload' if suffix[0] == 'uploads' else 'download', body, key)
            category, tid, *rest = suffix
            item = self.transfers.get(tid)
            if not item:
                raise FileError(404, '传输不存在或电脑连接器已重启，请重新传输。')
            action = rest[0] if rest else 'status'
            if action != 'status':
                item['touched'] = time.time()
            if category != 'transfers' and category != item['direction'] + 's':
                raise FileError(404, '传输类型不匹配。')
            if action == 'status':
                return self.public(item)
            if action == 'cancel':
                self.cancel(item)
                return self.public(item)
            if action == 'release':
                stream = self.streams.get(body['stream_id'])
                if stream and stream['transfer'] == item['id']:
                    self.streams.pop(body['stream_id'])
                return {}
            if item['state'] in {'cancelled', 'failed'}:
                raise FileError(410, item['detail'] or '传输已取消。')
            if action == 'chunk':
                if item['state'] == 'completed':
                    raise FileError(409, '文件已经上传完成。')
                return self.upload_chunk(item, body)
            if action == 'complete':
                return self.complete(item)
            if action == 'open':
                return self.open_stream(item, body['stream_id'])
            if action == 'progress':
                self.open_stream(item, body['stream_id'])
                return self.progress(item, body['offset'], body['length'])
            query = parse_qs(urlsplit(target).query)
            self.open_stream(item, query['stream_id'][0])
            return self.read_chunk(item, int(query['offset'][0]), int(query['length'][0]))

    async def request(self, method, target, body, key):
        try:
            result = await asyncio.to_thread(self.execute, method, target, body, key)
            return 200, result, None
        except FileError:
            raise
        except FileNotFoundError:
            raise FileError(404, '文件或目录不存在。') from None
        except PermissionError:
            raise FileError(403, '本机服务账号没有访问此文件或目录的权限。') from None
        except ValueError:
            raise FileError(400, '文件请求包含无效参数。') from None
        except OSError as exc:
            detail = '目标磁盘空间不足。' if exc.errno == errno.ENOSPC else '本机文件操作失败，请检查目录、权限和磁盘。'
            raise FileError(409, detail) from None
