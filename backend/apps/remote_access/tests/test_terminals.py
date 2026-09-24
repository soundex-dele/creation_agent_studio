import asyncio
import base64
import json
import os
import queue
import time
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.remote_access.protocol import TERMINAL_ROOT, validate_request
from apps.remote_access.terminals import TerminalError, TerminalManager
from apps.remote_access import terminals


def test_posix_partial_write_can_split_a_utf8_character(monkeypatch):
    from apps.remote_access import terminal_process
    process = terminal_process.TerminalProcess.__new__(terminal_process.TerminalProcess)
    process.process = SimpleNamespace(fd=123)
    write = Mock(side_effect=[1, 2, 1])
    monkeypatch.setattr(terminal_process, 'os', SimpleNamespace(name='posix', write=write))
    process.write('中x')
    assert [call.args[1] for call in write.call_args_list] == [b'\xe4\xb8\xadx', b'\xb8\xadx', b'x']


class FakeProcess:
    shell = 'test-shell'

    def __init__(self, cols, rows):
        self.incoming = queue.Queue()
        self.writes = []
        self.dimensions = (cols, rows)
        self.closed = False

    def read(self):
        data = self.incoming.get(timeout=10)
        if data is None:
            raise EOFError()
        return data

    def write(self, data):
        self.writes.append(data)

    def resize(self, cols, rows):
        self.dimensions = cols, rows

    def close(self):
        self.closed = True
        self.incoming.put(None)

    def exit_code(self):
        return 0


async def create(manager, key='create'):
    _, result, _ = await manager.request('POST', TERMINAL_ROOT, {'cols': 80, 'rows': 24}, key)
    return manager.sessions[result['id']]


@pytest.mark.asyncio
async def test_creation_and_input_are_idempotent_and_conflicts_are_rejected():
    manager = TerminalManager(FakeProcess)
    try:
        session = await create(manager)
        assert await create(manager) is session
        body = {'client_id': 'a' * 32, 'sequence': 1, 'data': 'echo 中文\r'}
        path = f'{TERMINAL_ROOT}{session.id}/input/'
        await asyncio.gather(*(manager.request('POST', path, body, 'batch') for _ in range(3)))
        assert session.process.writes == ['echo 中文\r']
        # Same text in a subsequent batch is a new user action.
        await manager.request('POST', path, {**body, 'sequence': 2}, 'next-batch')
        assert len(session.process.writes) == 2
        with pytest.raises(TerminalError, match='输入顺序'):
            await manager.request('POST', path, {**body, 'sequence': 2, 'data': 'other'}, 'changed')
        with pytest.raises(TerminalError):
            await manager.request('POST', path, {**body, 'sequence': 4}, 'gap')
        with pytest.raises(TerminalError):
            await manager.request('POST', TERMINAL_ROOT, {'cols': 100, 'rows': 24}, 'create')
    finally:
        await manager.close_all()


@pytest.mark.asyncio
async def test_detach_keeps_process_replay_is_bounded_and_close_reaps(monkeypatch):
    monkeypatch.setattr(terminals, 'MAX_OUTPUT', 12)
    manager = TerminalManager(FakeProcess)
    try:
        session = await create(manager)
        stream = session.stream(0)
        assert b'ready' in await anext(stream)
        await stream.aclose()
        assert not session.process.closed
        session.append('old-output')
        session.append('new-output')
        replay = session.stream(0)
        assert b'truncated' in await anext(replay)
        assert b'new-output' in await anext(replay)
        assert b'ready' in await anext(replay)
        assert session.size <= 12
        await replay.aclose()
        await manager.request('POST', f'{TERMINAL_ROOT}{session.id}/resize/', {'cols': 100, 'rows': 30}, 'resize')
        assert session.process.dimensions == (100, 30)
        await manager.request('POST', f'{TERMINAL_ROOT}{session.id}/close/', {}, 'close')
        assert session.process.closed and session.reader.done()
        await manager.request('POST', f'{TERMINAL_ROOT}{session.id}/close/', {}, 'close')
        with pytest.raises(TerminalError) as error:
            await create(manager)
        assert error.value.status == 410
    finally:
        await manager.close_all()


@pytest.mark.asyncio
async def test_session_limit_and_isolation():
    manager = TerminalManager(FakeProcess)
    try:
        sessions = [await create(manager, str(i)) for i in range(8)]
        with pytest.raises(TerminalError) as error:
            await create(manager, 'overflow')
        assert error.value.status == 409
        sessions[0].append('first-only')
        assert not sessions[1].output
        await manager.close_all()
        assert all(s.process.closed for s in sessions)
    finally:
        await manager.close_all()


@pytest.mark.parametrize('method,suffix,body', [
    ('POST', '', {'cols': True, 'rows': 24}),
    ('POST', '', {'cols': 80, 'rows': 24, 'command': 'bad'}),
    ('POST', 'a' * 32 + '/input/', {'client_id': 'a' * 32, 'sequence': 0, 'data': 'x'}),
    ('POST', 'a' * 32 + '/input/', {'client_id': 'a' * 32, 'sequence': 1, 'data': 'x' * 16385}),
    ('GET', 'a' * 32 + '/stream/?after=-1', None),
    ('GET', 'a' * 32 + '/stream/?search=x', None),
    ('GET', '?after=1', None),
    ('DELETE', 'a' * 32 + '/', None),
    ('POST', '../settings/', {}),
])
def test_terminal_allowlist_rejects_invalid_operations(method, suffix, body):
    with pytest.raises(ValueError):
        validate_request(method, TERMINAL_ROOT + suffix, body)


@pytest.mark.asyncio
async def test_real_platform_pty_unicode_resize_interrupt_and_exit():
    """Runs an actual native PTY on the test host; not a cross-platform mock."""
    from apps.remote_access.terminal_process import terminal_capability
    if not terminal_capability()['supported']:
        pytest.skip('Install platform PTY dependency to run native terminal smoke test')
    manager = TerminalManager()
    try:
        session = await create(manager)
        collected = ''
        async def until(marker):
            nonlocal collected
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                collected = ''.join(item[1] for item in session.output)
                if marker in collected:
                    return
                await asyncio.sleep(.05)
            pytest.fail(f'PTY did not produce expected marker {marker!r}')
        await until('>' if os.name == 'nt' else '')
        await session.input({'client_id': 'a' * 32, 'sequence': 1, 'data': '\x03'})
        await asyncio.sleep(.2)
        command = "Write-Output ('终端'+'验证'); Write-Output ('PTY_'+'OK')\r" if os.name == 'nt' else "printf '终端%s\\nPTY_%s\\n' '验证' 'OK'\r"
        await session.input({'client_id': 'a' * 32, 'sequence': 2, 'data': command})
        await until('PTY_OK')
        assert '终端验证' in collected
        await manager.request('POST', f'{TERMINAL_ROOT}{session.id}/resize/', {'cols': 101, 'rows': 31}, 'resize')
        command = "Start-Sleep 30\r" if os.name == 'nt' else 'sleep 30\r'
        await session.input({'client_id': 'a' * 32, 'sequence': 3, 'data': command})
        await asyncio.sleep(.5)
        await session.input({'client_id': 'a' * 32, 'sequence': 4, 'data': '\x03'})
        await asyncio.sleep(.3)
        command = "Write-Output ('AFTER_'+'INTERRUPT')\r" if os.name == 'nt' else "printf 'AFTER_%s\\n' INTERRUPT\r"
        await session.input({'client_id': 'a' * 32, 'sequence': 5, 'data': command})
        await until('AFTER_INTERRUPT')
        # A real full-screen child application, rather than simulated PTY output.
        child = (
            "import sys,os,time\n"
            "print('\\x1b[?1049h\\x1b[2J\\x1b[31mTUI_READY', flush=True)\n"
            + ("import msvcrt\nkey=msvcrt.getwch()\n" if os.name == 'nt'
               else "import tty,termios\nold=termios.tcgetattr(0)\ntty.setraw(0)\nkey=sys.stdin.read(1)\ntermios.tcsetattr(0,termios.TCSADRAIN,old)\n")
            + "print('\\x1b[0m\\x1b[?1049lTUI_KEY_'+key, flush=True)\n"
        )
        encoded = base64.b64encode(child.encode()).decode()
        code = f'import base64;exec(base64.b64decode("{encoded}"))'
        command = f"{'& ' if os.name == 'nt' else ''}'{sys.executable}' -u -c '{code}'\r"
        await session.input({'client_id': 'a' * 32, 'sequence': 6, 'data': command})
        await until('TUI_READY')
        await session.input({'client_id': 'a' * 32, 'sequence': 7, 'data': 'q'})
        await until('TUI_KEY_q')
        assert '\x1b[?1049h' in collected
        await session.input({'client_id': 'a' * 32, 'sequence': 8, 'data': 'exit\r'})
        await asyncio.wait_for(session.reader, 10)
        assert session.exited
    finally:
        await manager.close_all()
