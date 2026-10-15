"""Bounded, data-only ingestion. Never check out, install or execute repository code."""
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

import requests
from django.conf import settings
from apps.applications.runtime_paths import resolve_runtime_path

EXCLUDED = {'.git', '.hg', '.svn', 'node_modules', 'venv', '.venv', '__pycache__',
            'dist', 'build', '.next', '.cache', 'target', 'vendor', '.idea',
            '.ssh', '.aws', '.azure', '.gcloud', '.codex'}
BINARY_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.mp4', '.mov', '.mp3',
                   '.wav', '.zip', '.gz', '.7z', '.pdf', '.exe', '.dll', '.so', '.woff', '.woff2',
                   '.ttf', '.otf', '.db', '.sqlite3', '.pyc', '.lockb'}


def limits():
    defaults = {'archive_bytes': 100 * 1024**2, 'expanded_bytes': 200 * 1024**2,
                'files': 20000, 'file_bytes': 2 * 1024**2, 'text_bytes': 20 * 1024**2,
                'analysis_chars': 180000, 'rounds': 3}
    return {k: int(getattr(settings, 'REPO_EXPLAINER_' + k.upper(), v)) for k, v in defaults.items()}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def excluded(name):
    parts = PurePosixPath(name).parts
    base = parts[-1].lower()
    return any(p in EXCLUDED for p in parts) or base.startswith('.env') or base in {
        '.npmrc', '.pypirc', '.netrc', '.git-credentials', 'credentials', 'credentials.json',
        'secrets.json', 'secrets.yaml', 'secrets.yml', 'id_rsa', 'id_ed25519',
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock', 'uv.lock',
    } or base.endswith(('.pem', '.key', '.p12', '.pfx'))


def safe_name(name):
    name = name.replace('\\', '/')
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or ':' in name or '\x00' in name:
        raise ValueError('归档包含不安全的文件路径。')
    return p.as_posix()


def decode(raw):
    if b'\x00' in raw:
        return None
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return None
    return text if not text.startswith('version https://git-lfs.github.com/spec/') else None


def collect(entries, check):
    files, skipped, total, count = {}, [], 0, 0
    bound = limits()
    for name, size, read in entries:
        check()
        count += 1
        if count > bound['files']:
            raise ValueError('文件数量超过导入限制，请缩小仓库范围。')
        reason = '排除目录或凭据/依赖文件' if excluded(name) else ('二进制资源' if PurePosixPath(name).suffix.lower() in BINARY_SUFFIXES else '')
        if not reason and size > bound['file_bytes']:
            raise ValueError(f'文本候选文件超过单文件限制：{name}')
        if reason:
            skipped.append({'path': name, 'reason': reason})
            continue
        raw = read()
        if len(raw) > bound['file_bytes']:
            raise ValueError('文件在读取期间变大或超过限制。')
        text = decode(raw)
        if text is None:
            skipped.append({'path': name, 'reason': '二进制、非 UTF-8 或 LFS 指针'})
            continue
        total += len(raw)
        if total > bound['text_bytes']:
            raise ValueError('源码文本总量超过限制，请缩小仓库范围。')
        files[name] = {'text': text, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    if not files:
        raise ValueError('没有可分析的 UTF-8 源码或文档。')
    return files, {'files_included': len(files), 'text_bytes': total, 'excluded': skipped,
                   'notes': ['仅保存可读取文本；不获取子模块、LFS 对象，不运行项目。']}


def from_zip(raw, check, strip_root=False):
    bound = limits()
    if len(raw) > bound['archive_bytes']:
        raise ValueError('ZIP 超过上传大小限制。')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > bound['files'] or sum(i.file_size for i in infos) > bound['expanded_bytes']:
            raise ValueError('归档解压大小或文件数量超过限制。')
        names, seen = [], set()
        for info in infos:
            check()
            name = safe_name(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)) or info.flag_bits & 1:
                raise ValueError('不支持链接、特殊文件或加密 ZIP。')
            if name.casefold() in seen:
                raise ValueError('ZIP 包含重复或大小写冲突的路径。')
            seen.add(name.casefold())
            if not info.is_dir():
                names.append((name, info))
        roots = {name.split('/')[0] for name, _ in names}
        drop = len(roots) == 1 and all('/' in name for name, _ in names)
        if strip_root and not drop:
            raise ValueError('GitHub 源码归档结构无效。')
        return collect(((name.split('/', 1)[1] if drop else name, info.file_size,
                         lambda i=info: archive.read(i)) for name, info in names), check)


def git(root, *args):
    # These plumbing commands do not invoke repository hooks or filters.
    env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'}
    return subprocess.run(['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=',
                           '-c', 'core.untrackedCache=false', '-C', str(root), *args], capture_output=True, timeout=30,
                          check=True, env=env).stdout


def from_local(raw, user, check):
    root = resolve_runtime_path(raw, user)
    if not root.is_dir():
        raise ValueError('本地仓库目录不存在。')
    try:
        before = git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
        commit = git(root, 'rev-parse', 'HEAD').decode().strip()
    except (OSError, subprocess.SubprocessError):
        raise ValueError('请选择有效且当前账号可读取的 Git 仓库目录。') from None
    names = sorted(set(before.decode('utf-8').split('\x00')) - {''})
    if len(names) > limits()['files']:
        raise ValueError('仓库文件数量超过限制。')
    checks, skipped = {}, []

    def entries():
        for raw_name in names:
            check()
            name = safe_name(raw_name)
            path = root / name
            parts = [path, *list(path.parents)[:len(PurePosixPath(name).parts) - 1]]
            if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in parts):
                skipped.append({'path': name, 'reason': '符号链接或目录联接'})
                continue
            if not path.exists() or path.is_dir():
                skipped.append({'path': name, 'reason': '已删除文件或未读取的子模块'})
                continue
            resolved = resolve_runtime_path(str(path), user)
            if root not in resolved.parents:
                raise ValueError('文件超出仓库边界。')
            info = path.stat()
            checks[name] = (info.st_size, info.st_mtime_ns, info.st_ino)
            def read(p=path, n=name):
                if p.resolve() != p or p.is_symlink():
                    raise ValueError('源码路径在读取期间发生变化。')
                with p.open('rb') as f:
                    return f.read(limits()['file_bytes'] + 1)
            yield name, info.st_size, read
    files, coverage = collect(entries(), check)
    for name, signature in checks.items():
        check()
        try:
            info = (root / name).stat()
        except OSError:
            raise ValueError('复制期间源码发生变化，请重新导入。') from None
        if (info.st_size, info.st_mtime_ns, info.st_ino) != signature:
            raise ValueError('复制期间源码发生变化，请重新导入。')
    if before != git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard'):
        raise ValueError('复制期间仓库文件列表发生变化，请重新导入。')
    coverage['excluded'].extend(skipped)
    return files, coverage, {'kind': 'local', 'path': str(root), 'commit': commit, 'working_tree': True}


def github_source(url, ref, check):
    parsed = urlsplit(url)
    parts = parsed.path.strip('/').removesuffix('.git').split('/')
    if parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.query or parsed.fragment or len(parts) != 2 or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', p) and p not in {'.', '..'} for p in parts):
        raise ValueError('请输入 https://github.com/所有者/仓库 地址，分支另行填写。')
    repo = '/'.join(parts)
    session = requests.Session()
    session.trust_env = False  # No ambient .netrc credentials or proxy authentication.
    def get(url, maximum):
        check()
        with session.get(url, timeout=(10, 60), stream=True, allow_redirects=False,
                         headers={'Accept': 'application/vnd.github+json'}) as response:
            if response.status_code != 200:
                raise ValueError(f'GitHub 读取失败（HTTP {response.status_code}），请检查公开权限、引用或请求限额。')
            output = bytearray()
            for chunk in response.iter_content(65536):
                check()
                output.extend(chunk)
                if len(output) > maximum:
                    raise ValueError('GitHub 响应超过大小限制。')
            return bytes(output)
    try:
        info = json.loads(get(f'https://api.github.com/repos/{repo}', 1024**2))
        selected = ref or info['default_branch']
        commit = json.loads(get(f'https://api.github.com/repos/{repo}/commits/{quote(selected, safe="")}', 4 * 1024**2))['sha']
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise ValueError('GitHub 提交标识无效。')
        raw = get(f'https://codeload.github.com/{repo}/zip/{commit}', limits()['archive_bytes'])
        files, coverage = from_zip(raw, check, strip_root=True)
        return files, coverage, {'kind': 'github', 'url': f'https://github.com/{repo}', 'ref': selected, 'commit': commit}
    finally:
        session.close()
