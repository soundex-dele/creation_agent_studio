"""Safe directory listing and previews for managed project workspaces."""

from core.observability import log_operation
import base64
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from apps.projects.services.workspace_paths import (
    application_working_directory,
    conversation_working_directory,
)


MAX_ENTRIES = 500
MAX_TEXT_PREVIEW_BYTES = 512 * 1024
MAX_IMAGE_PREVIEW_BYTES = 5 * 1024 * 1024
SKIPPED_DIRECTORIES = {'.git', '.venv', 'venv', 'node_modules', '__pycache__'}
TEXT_EXTENSIONS = {
    '.txt', '.md', '.markdown', '.json', '.jsonl', '.csv', '.tsv', '.yaml',
    '.yml', '.toml', '.ini', '.cfg', '.log', '.py', '.js', '.jsx', '.ts',
    '.tsx', '.css', '.scss', '.html', '.htm', '.xml', '.sql', '.sh', '.ps1',
    '.bat', '.cmd', '.srt', '.vtt',
}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}


class WorkspaceFileError(ValueError):
    pass


def _project_workspace_root(project):
    return Path(application_working_directory(project)).resolve()


def _conversation_workspace_root(conversation):
    return Path(conversation_working_directory(conversation)).resolve()


def _preview_kind(path, mime_type):
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS or mime_type.startswith('image/'):
        return 'image'
    if suffix in TEXT_EXTENSIONS or mime_type.startswith('text/'):
        return 'text'
    return 'binary'


def _entry(root, path, is_directory):
    relative = path.relative_to(root).as_posix()
    try:
        stat = path.stat()
    except OSError:
        return None
    mime_type = '' if is_directory else (mimetypes.guess_type(path.name)[0] or '')
    return {
        'name': path.name,
        'path': relative,
        'is_directory': is_directory,
        'depth': len(path.relative_to(root).parts) - 1,
        'size': 0 if is_directory else stat.st_size,
        'modified_at': datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc).isoformat(),
        'mime_type': mime_type,
        'preview_kind': 'directory' if is_directory else _preview_kind(path, mime_type),
    }


def _list_workspace_files(root):
    entries = []
    def visit(directory, depth=0):
        if depth > 20 or len(entries) >= MAX_ENTRIES:
            return
        try:
            children = [path for path in directory.iterdir() if not path.is_symlink()]
        except OSError:
            return
        directories = sorted(
            (path for path in children
             if path.is_dir() and path.name not in SKIPPED_DIRECTORIES),
            key=lambda path: path.name.casefold(),
        )
        files = sorted(
            (path for path in children if path.is_file()),
            key=lambda path: path.name.casefold(),
        )
        for path in directories:
            item = _entry(root, path, True)
            if item:
                entries.append(item)
            if len(entries) >= MAX_ENTRIES:
                return
            visit(path, depth + 1)
        for path in files:
            item = _entry(root, path, False)
            if item:
                entries.append(item)
            if len(entries) >= MAX_ENTRIES:
                return

    visit(root)

    file_count = sum(not item['is_directory'] for item in entries)
    return {
        'working_directory': str(root),
        'entries': entries,
        'file_count': file_count,
        'truncated': len(entries) >= MAX_ENTRIES,
    }


def _read_workspace_file(root, relative_path):
    if not relative_path:
        raise WorkspaceFileError('请指定要预览的文件。')
    target = (root / relative_path).resolve()
    if target == root or root not in target.parents:
        raise WorkspaceFileError('文件路径超出了工作目录。')
    if not target.is_file():
        raise FileNotFoundError(relative_path)

    mime_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
    kind = _preview_kind(target, mime_type)
    max_bytes = MAX_IMAGE_PREVIEW_BYTES if kind == 'image' else MAX_TEXT_PREVIEW_BYTES
    with target.open('rb') as handle:
        data = handle.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    data = data[:max_bytes]

    response = {
        'name': target.name,
        'path': target.relative_to(root).as_posix(),
        'size': target.stat().st_size,
        'mime_type': mime_type,
        'preview_kind': kind,
        'truncated': truncated,
    }
    if kind == 'text':
        response['content'] = data.decode('utf-8', errors='replace')
    elif kind == 'image' and not truncated:
        encoded = base64.b64encode(data).decode('ascii')
        response['data_url'] = f'data:{mime_type};base64,{encoded}'
    return response


@log_operation
def list_workspace_files(project):
    return _list_workspace_files(_project_workspace_root(project))


@log_operation
def read_workspace_file(project, relative_path):
    return _read_workspace_file(_project_workspace_root(project), relative_path)


@log_operation
def list_conversation_workspace_files(conversation):
    return _list_workspace_files(_conversation_workspace_root(conversation))


@log_operation
def read_conversation_workspace_file(conversation, relative_path):
    return _read_workspace_file(
        _conversation_workspace_root(conversation), relative_path)
