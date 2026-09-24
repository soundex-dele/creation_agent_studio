import base64
import errno
import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from apps.remote_access.file_protocol import FILE_CHUNK, MAX_FILE_SIZE
from apps.remote_access.files import FileError, FileManager, IDLE_TTL, list_directory, safe_path
from apps.remote_access.protocol import FILE_ROOT, validate_request


def call(manager, suffix, body=None, key='operation'):
    if '/read/?' in suffix:
        suffix += '&stream_id=' + suffix.split('/')[1]
    if suffix.endswith('/progress/'):
        body = {**body, 'stream_id': suffix.split('/')[1]}
    return manager.execute('GET' if body is None else 'POST', FILE_ROOT + suffix, body, key)


def create(manager, directory, size=0, name='中文.txt', key='create'):
    return call(manager, 'uploads/', {'path': str(directory), 'name': name, 'size': size}, key)


def block(data, offset=0):
    return {'offset': offset, 'data': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}


def sparse_resize(output, size):
    if os.name != 'nt':
        output.truncate(size)
        return
    # CRT _chsize_s zero-fills even a sparse file. SetEndOfFile preserves actual holes.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.windll.kernel32
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(output.fileno()))
    returned = wintypes.DWORD()
    assert kernel.DeviceIoControl(handle, 0x900C4, None, 0, None, 0, ctypes.byref(returned), None)
    kernel.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong, ctypes.c_void_p, wintypes.DWORD]
    assert kernel.SetFilePointerEx(handle, size, None, 0)
    assert kernel.SetEndOfFile(handle)


@pytest.fixture
def manager(tmp_path):
    return FileManager(tmp_path / 'journal')


def test_upload_replay_offsets_checksum_and_conflict(manager, tmp_path):
    data = b'a' * FILE_CHUNK + b'b' * FILE_CHUNK + '你好'.encode()
    item = create(manager, tmp_path, len(data))
    assert create(manager, tmp_path, len(data)) == item
    with pytest.raises(FileError, match='参数'):
        create(manager, tmp_path, 1)
    suffix = f"uploads/{item['id']}/"
    with pytest.raises(FileError, match='完整'):
        call(manager, suffix + 'complete/', {})
    for offset in range(0, len(data), FILE_CHUNK):
        chunk = block(data[offset:offset + FILE_CHUNK], offset)
        result = call(manager, suffix + 'chunk/', chunk)
        assert result['offset'] == offset + len(data[offset:offset + FILE_CHUNK])
        assert call(manager, suffix + 'chunk/', chunk) == result
    # Arbitrarily old duplicate blocks are checked against disk, without a per-block memory ledger.
    assert call(manager, suffix + 'chunk/', block(data[:FILE_CHUNK]))['offset'] == len(data)
    with pytest.raises(FileError, match='不一致'):
        call(manager, suffix + 'chunk/', block(b'z' * FILE_CHUNK))
    with pytest.raises(FileError, match='校验'):
        call(manager, suffix + 'chunk/', {**block(b'x'), 'sha256': '0' * 64})
    finished = call(manager, suffix + 'complete/', {})
    assert Path(finished['path']).read_bytes() == data
    assert call(manager, suffix + 'complete/', {}) == finished
    call(manager, f"transfers/{item['id']}/cancel/", {})
    assert Path(finished['path']).read_bytes() == data


def test_empty_files_concurrent_names_and_direction_limit(manager, tmp_path):
    (tmp_path / '中文.txt').write_bytes(b'keep')
    first = create(manager, tmp_path)
    second = create(manager, tmp_path, key='second')
    assert len(call(manager, 'transfers/')['transfers']) == 2
    with pytest.raises(FileError) as error:
        create(manager, tmp_path, key='third')
    assert error.value.status == 429
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda item: call(manager, f"uploads/{item['id']}/complete/", {}), [first, second]))
    assert {item['name'] for item in results} == {'中文 (1).txt', '中文 (2).txt'}
    assert (tmp_path / '中文.txt').read_bytes() == b'keep'
    assert all(Path(item['path']).stat().st_size == 0 for item in results)
    assert not call(manager, 'transfers/')['transfers']
    create(manager, tmp_path, MAX_FILE_SIZE, key='boundary')
    with pytest.raises(ValueError):
        create(manager, tmp_path, MAX_FILE_SIZE + 1, key='oversize')


@pytest.mark.asyncio
async def test_cleanup_cancel_restart_and_idle(manager, tmp_path):
    first = create(manager, tmp_path, 1)
    part = Path(manager.transfers[first['id']]['part'])
    call(manager, f"transfers/{first['id']}/cancel/", {})
    assert not part.exists()
    item = create(manager, tmp_path, 1, key='orphan')
    part = Path(manager.transfers[item['id']]['part'])
    restarted = FileManager(manager.state_dir)
    restarted.cleanup()
    assert part.exists()
    os.utime(part, (time.time() - IDLE_TTL - 1,) * 2)
    restarted.cleanup()
    assert not part.exists()
    item = create(restarted, tmp_path, 1, key='shutdown')
    await restarted.close_all()
    assert not restarted.transfers
    assert not list(tmp_path.glob('.agent-studio-upload-*.part'))


def test_pagination_and_resolved_paths(manager, tmp_path):
    folder = tmp_path / '子目录'
    folder.mkdir()
    for number in range(105):
        (folder / f'{number:03}.txt').touch()
    first = list_directory(str(folder), '')
    assert len(first['entries']) == 100
    second = list_directory(str(folder), first['next_cursor'])
    assert len(second['entries']) == 5 and not second['next_cursor']
    assert first['path'] == str(folder.resolve())
    assert safe_path(str(folder / '..')) == tmp_path.resolve()
    assert not set(e['name'] for e in first['entries']) & set(e['name'] for e in second['entries'])
    with pytest.raises(FileError):
        list_directory(str(folder), 'bad')
    assert call(manager, 'roots/')['roots']


def test_download_bounded_reads_progress_mutation_and_size(manager, tmp_path):
    source = tmp_path / '源.dat'
    source.write_bytes(b'hello world')
    item = call(manager, 'downloads/', {'path': str(source)}, 'download')
    prefix = f"downloads/{item['id']}/"
    assert base64.b64decode(call(manager, prefix + 'read/?offset=6&length=5')['data']) == b'world'
    call(manager, prefix + 'progress/', {'offset': 6, 'length': 5})
    assert call(manager, prefix + 'progress/', {'offset': 6, 'length': 5})['offset'] == 5
    assert call(manager, prefix + 'progress/', {'offset': 0, 'length': 6})['state'] == 'completed'
    source.write_bytes(b'changed')
    with pytest.raises(FileError, match='变化'):
        call(manager, prefix + 'read/?offset=0&length=1')
    source = tmp_path / 'sparse'
    with source.open('wb') as output:
        sparse_resize(output, MAX_FILE_SIZE)
    boundary = call(manager, 'downloads/', {'path': str(source)}, 'boundary')
    assert boundary['size'] == MAX_FILE_SIZE
    data = call(manager, f"downloads/{boundary['id']}/read/?offset={MAX_FILE_SIZE - 1}&length=1")
    assert base64.b64decode(data['data']) == b'\0'
    with source.open('ab') as output:
        sparse_resize(output, MAX_FILE_SIZE + 1)
    with pytest.raises(FileError) as error:
        call(manager, 'downloads/', {'path': str(source)}, 'oversize')
    assert error.value.status == 413


@pytest.mark.asyncio
@pytest.mark.parametrize('number,status', [(errno.ENOSPC, 409), (errno.EACCES, 403), (errno.ENOENT, 404)])
async def test_disk_errors_keep_existing_files(manager, tmp_path, monkeypatch, number, status):
    target = tmp_path / '中文.txt'
    target.write_bytes(b'keep')
    def fail(*args, **kwargs):
        raise OSError(number, 'test')
    monkeypatch.setattr(os, 'open', fail)
    with pytest.raises(FileError) as error:
        await manager.request('POST', FILE_ROOT + 'uploads/', {'path': str(tmp_path), 'name': target.name, 'size': 1}, 'key')
    assert error.value.status == status
    assert target.read_bytes() == b'keep'


@pytest.mark.skipif(os.name != 'nt', reason='Windows paths')
@pytest.mark.parametrize('path', [r'\\.\NUL', r'\\?\C:\test', r'C:\test:stream', r'C:\CON.txt', r'C:\a\LPT1'])
def test_windows_special_paths(path):
    with pytest.raises(FileError):
        safe_path(path)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX FIFO')
def test_fifo_and_symlink(manager, tmp_path):
    fifo = tmp_path / 'fifo'
    os.mkfifo(fifo)
    with pytest.raises(FileError, match='普通'):
        call(manager, 'downloads/', {'path': str(fifo)}, 'fifo')
    link = tmp_path / 'link'
    directory = tmp_path / 'actual'
    directory.mkdir()
    link.symlink_to(directory, target_is_directory=True)
    assert list_directory(str(link), '')['path'] == str(directory)


@pytest.mark.parametrize('method,suffix,body', [
    ('POST', 'delete/', {}), ('GET', 'roots/?path=/', None), ('POST', 'uploads/', {'path': '/', 'name': 'x', 'size': True}),
    ('GET', 'downloads/' + 'a' * 32 + '/read/?offset=0&length=262145', None),
    ('POST', 'uploads/' + 'a' * 32 + '/chunk/', {'offset': 0, 'data': 'a' * (FILE_CHUNK * 2), 'sha256': '0' * 64}),
])
def test_strict_file_whitelist(method, suffix, body):
    with pytest.raises(ValueError):
        validate_request(method, FILE_ROOT + suffix, body)


def test_active_download_stream_limit_including_completed_tasks(manager, tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'a')
    item = call(manager, 'downloads/', {'path': str(source)}, 'download')
    path = f"downloads/{item['id']}/"
    for key in ('a' * 32, 'b' * 32):
        call(manager, path + 'open/', {'stream_id': key})
    with pytest.raises(FileError) as error:
        call(manager, path + 'open/', {'stream_id': 'c' * 32})
    assert error.value.status == 429
    call(manager, path + 'release/', {'stream_id': 'a' * 32})
    call(manager, path + 'open/', {'stream_id': 'c' * 32})
    call(manager, f"transfers/{item['id']}/cancel/", {})
    assert not manager.streams


def test_upload_buffer_memory_is_independent_of_declared_file_size(manager, tmp_path):
    import tracemalloc
    item = create(manager, tmp_path, MAX_FILE_SIZE)
    data = b'x' * FILE_CHUNK
    tracemalloc.start()
    try:
        for index in range(24):
            call(manager, f"uploads/{item['id']}/chunk/", block(data, index * FILE_CHUNK))
        _, peak = tracemalloc.get_traced_memory()
        assert peak < 4 * 1024**2
    finally:
        tracemalloc.stop()
        call(manager, f"transfers/{item['id']}/cancel/", {})


def test_disappearing_download_reports_failure_in_task_status(manager, tmp_path):
    source = tmp_path / 'disappearing'
    source.write_bytes(b'a')
    item = call(manager, 'downloads/', {'path': str(source)}, 'download')
    source.unlink()
    with pytest.raises(FileError) as error:
        call(manager, f"downloads/{item['id']}/read/?offset=0&length=1")
    assert error.value.status == 404
    status = call(manager, f"transfers/{item['id']}/")
    assert status['state'] == 'failed' and status['detail']


def test_post_commit_cleanup_failure_does_not_publish_twice(manager, tmp_path, monkeypatch):
    item = create(manager, tmp_path)
    original_unlink = Path.unlink
    def denied_manifest(path, *args, **kwargs):
        if path.suffix == '.json':
            raise PermissionError('journal read-only')
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', denied_manifest)
    result = call(manager, f"uploads/{item['id']}/complete/", {})
    assert result['state'] == 'completed'
    assert call(manager, f"uploads/{item['id']}/complete/", {}) == result
    assert len(list(tmp_path.glob('*.txt'))) == 1
