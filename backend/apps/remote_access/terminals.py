"""Connector-owned, bounded, ephemeral terminal sessions (no relay persistence)."""
import asyncio
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import uuid
from urllib.parse import parse_qs, urlsplit

from .protocol import TERMINAL_ROOT, validate_request
from .terminal_process import TerminalProcess

MAX_OUTPUT = 1024 * 1024
MAX_SESSIONS = 8


class TerminalError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


class Session:
    def __init__(self, process):
        self.id = uuid.uuid4().hex
        self.process = process
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.output = deque()
        self.size = self.sequence = 0
        self.exited = False
        self.exit_code = None
        self.changed = asyncio.Event()
        self.lock = asyncio.Lock()
        self.clients = {}
        self.reader = asyncio.create_task(self.read())

    def info(self):
        return {'id': self.id, 'shell': self.process.shell, 'created_at': self.created_at,
                'exited': self.exited, 'exit_code': self.exit_code}

    def append(self, data):
        size = len(data.encode('utf-8'))
        self.sequence += 1
        self.output.append((self.sequence, data, size))
        self.size += size
        while self.output and self.size > MAX_OUTPUT:
            self.size -= self.output.popleft()[2]
        self.changed.set()

    async def read(self):
        try:
            while not self.exited:
                data = await asyncio.to_thread(self.process.read)
                if data:
                    self.append(data)
                else:
                    await asyncio.sleep(0.02)
        except (EOFError, OSError):
            pass
        finally:
            self.exited = True
            try:
                self.exit_code = await asyncio.to_thread(self.process.exit_code)
            except (OSError, AttributeError):
                pass
            await asyncio.to_thread(self.process.close)
            self.changed.set()

    async def close(self):
        self.exited = True
        await asyncio.to_thread(self.process.close)
        self.changed.set()
        await self.reader

    async def input(self, body):
        async with self.lock:
            client, seq, data = body['client_id'], body['sequence'], body['data']
            digest = hashlib.sha256(data.encode()).hexdigest()
            previous, previous_digest = self.clients.get(client, (0, ''))
            if seq == previous and digest == previous_digest:
                return {'sequence': seq}
            if seq != previous + 1:
                raise TerminalError(409, '输入顺序已变化，请重新连接终端。')
            if client not in self.clients and len(self.clients) >= 128:
                raise TerminalError(409, '此会话连接次数过多，请新建终端。')
            if self.exited:
                raise TerminalError(410, '终端进程已退出。')
            # Reserve before writing: partial failures must never re-execute input.
            self.clients[client] = (seq, digest)
            try:
                await asyncio.to_thread(self.process.write, data)
            except Exception as exc:
                await self.close()
                raise TerminalError(410, '终端输入失败，会话已结束，请检查命令执行结果。') from exc
            return {'sequence': seq}

    async def stream(self, after):
        if after > self.sequence:
            raise TerminalError(409, '终端输出游标已失效，请重新打开会话。')
        ready = False
        while True:
            self.changed.clear()
            oldest = self.output[0][0] if self.output else self.sequence + 1
            if after < oldest - 1:
                after = oldest - 1
                yield self.event({'type': 'truncated', 'sequence': after})
            for seq, data, _ in tuple(self.output):
                if seq > after:
                    yield self.event({'type': 'output', 'sequence': seq, 'data': data})
                    after = seq
            if self.exited:
                yield self.event({'type': 'exit', 'exit_code': self.exit_code})
                return
            if not ready:
                # Historical terminal queries must not send new input to the shell.
                # Enable browser input only after replay has finished.
                ready = True
                yield self.event({'type': 'ready'})
            try:
                await asyncio.wait_for(self.changed.wait(), 15)
            except TimeoutError:
                yield b': keepalive\n\n'

    @staticmethod
    def event(value):
        return ('data: ' + json.dumps(value, ensure_ascii=False) + '\n\n').encode()


class TerminalManager:
    def __init__(self, factory=TerminalProcess):
        self.factory = factory
        self.sessions = {}
        self.creations = {}
        self.lock = asyncio.Lock()
        self.grant = None

    async def close_all(self):
        async with self.lock:
            sessions, self.sessions = list(self.sessions.values()), {}
            self.creations.clear()
            await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)

    async def request(self, method, target, body, key):
        path = validate_request(method, target, body)
        suffix = path[len(TERMINAL_ROOT):].strip('/').split('/')
        if method == 'POST' and (not isinstance(key, str) or not 1 <= len(key) <= 160):
            raise TerminalError(400, '缺少操作幂等标识。')
        if path == TERMINAL_ROOT:
            if method == 'GET':
                return 200, {'sessions': [s.info() for s in self.sessions.values()]}, None
            async with self.lock:
                if key in self.creations:
                    previous, session_id = self.creations[key]
                    if previous != body:
                        raise TerminalError(409, '同一请求不能更改终端参数。')
                    if session_id not in self.sessions:
                        raise TerminalError(410, '该终端已关闭，请新建会话。')
                    return 201, self.sessions[session_id].info(), None
                if sum(not s.exited for s in self.sessions.values()) >= MAX_SESSIONS:
                    raise TerminalError(409, '最多同时运行 8 个终端，请先关闭一个会话。')
                if len(self.creations) >= 4096:
                    raise TerminalError(409, '终端创建次数达到上限，请在本机重启连接器。')
                # Keep at most eight recent exited sessions, in addition to running sessions.
                exited = [s.id for s in self.sessions.values() if s.exited]
                for sid in exited[:-7]:
                    self.sessions.pop(sid)
                process = await asyncio.to_thread(self.factory, body['cols'], body['rows'])
                session = Session(process)
                self.sessions[session.id] = session
                self.creations[key] = (dict(body), session.id)
                return 201, session.info(), None
        sid, action = suffix
        session = self.sessions.get(sid)
        if not session:
            if action == 'close':
                return 200, {'closed': True}, None
            raise TerminalError(404, '终端不存在或本机服务已重启，请新建会话。')
        if action == 'stream':
            after = int(parse_qs(urlsplit(target).query).get('after', ['0'])[0])
            if after > session.sequence:
                raise TerminalError(409, '终端输出游标已失效，请重新打开会话。')
            return 200, None, session.stream(after)
        if action == 'input':
            result = await session.input(body)
        elif action == 'resize':
            async with session.lock:
                if session.exited:
                    raise TerminalError(410, '终端进程已退出。')
                await asyncio.to_thread(session.process.resize, body['cols'], body['rows'])
            result = {'resized': True}
        else:
            await session.close()
            self.sessions.pop(sid, None)
            result = {'closed': True}
        return 200, result, None
