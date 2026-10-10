"""Windows-only filesystem boundary. Never delete by a pathname after validation."""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager, ExitStack
import hashlib
import os
from pathlib import Path
import platform
import shutil
import stat
import tempfile

from django.conf import settings


class UnsafePath(ValueError):
    pass


def supported():
    return os.name == "nt"


def host_id():
    # MachineGuid distinguishes hosts even if their display names coincide.
    if supported():
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            machine = winreg.QueryValueEx(key, "MachineGuid")[0]
    else:
        machine = platform.node()
    return hashlib.sha256(str(machine).encode()).hexdigest()


def _kernel():
    if not supported():
        raise UnsafePath("首版仅支持 Windows 后端主机。")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.CreateFileW.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    k.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    return k


class FileInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                ("accessed", wintypes.FILETIME), ("modified", wintypes.FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


def canonical(value):
    text = str(value)
    # Reject UNC/device namespaces and alternate data streams before normalization.
    if not supported() or text.startswith(("\\\\", "//")) or not Path(text).is_absolute():
        raise UnsafePath("请选择本机固定磁盘中的绝对路径。")
    if ":" in text[2:] or "\x00" in text or any(p.endswith((".", " ")) for p in Path(text).parts[1:]):
        raise UnsafePath("目录路径无效。")
    path = Path(os.path.abspath(text))
    if _kernel().GetDriveTypeW(path.anchor) != 3:
        raise UnsafePath("仅支持本地固定磁盘，不支持网络盘或可移动磁盘。")
    return path


def under(path, root):
    return path == root or root in path.parents


def no_reparse(path):
    for part in [*reversed(path.parents), path]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise UnsafePath("跳过链接、junction 或其他重解析点。")


def cache_roots():
    if not supported():
        return []
    candidates = [tempfile.gettempdir(), str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp")]
    result = []
    for value in candidates:
        try:
            path = canonical(value)
            no_reparse(path)
            if path.is_dir() and str(path) not in result:
                result.append(str(path))
        except (OSError, UnsafePath):
            pass
    return result


def protected_roots():
    values = [settings.BASE_DIR.parent, settings.APP_CENTER_ROOT]
    for name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        if os.environ.get(name):
            values.append(os.environ[name])
    for name in ("MY_DRIVE_ROOT", "MEDIA_ROOT", "ARTIFACT_ROOT", "AGENT_WORKSPACE_ROOT", "MEETING_AUDIO_ROOT",
                 "TEACHING_DATA_ROOT", "DISK_CLEANER_PROTECTED_ROOTS"):
        value = getattr(settings, name, None)
        if value:
            values.extend(value if isinstance(value, (list, tuple)) else [value])
    for db in settings.DATABASES.values():
        if db.get("ENGINE", "").endswith("sqlite3") and db.get("NAME"):
            values.append(Path(db["NAME"]).absolute().parent)
    return [Path(os.path.abspath(str(v))) for v in values]


def protected(path, cache_root=None):
    if any(p.lower() in {"system volume information", "$recycle.bin", "$extend", "recovery"} for p in path.parts):
        return True
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    for root in protected_roots():
        if under(path, root):
            # Only the Windows system-directory rule has a narrowly defined exception.
            if root == windows and cache_root == windows / "Temp" and under(path, cache_root):
                continue
            return True
    return False


def validate_root(value, mode):
    root = canonical(value)
    no_reparse(root)
    if not root.is_dir():
        raise UnsafePath("扫描目录不存在。")
    if mode != "analysis" and root == Path(root.anchor):
        raise UnsafePath("清理大文件必须明确选择一个非盘符根目录。")
    cache = root if mode == "cache" else None
    if mode == "cache" and str(root) not in cache_roots():
        raise UnsafePath("缓存扫描仅允许预设临时目录。")
    if protected(root, cache):
        raise UnsafePath("该目录属于受保护的系统或应用存储。")
    return root


@contextmanager
def handle(path, *, deleting=False, lock_directory=False):
    k = _kernel()
    # Deny concurrent writes/deletes during deletion and while holding ancestors.
    share = 1 if deleting or lock_directory else 7
    h = k.CreateFileW(str(path), 0x80 | (0x10000 if deleting else 0), share, None, 3, 0x02200000, None)
    if h == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield h
    finally:
        k.CloseHandle(h)


def info_from_handle(h, path):
    k = _kernel()
    info = FileInfo()
    if not k.GetFileInformationByHandle(h, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if info.attributes & 0x400:
        raise UnsafePath("跳过重解析点。")
    buffer = ctypes.create_unicode_buffer(32768)
    length = k.GetFinalPathNameByHandleW(h, buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise UnsafePath("无法校验文件最终路径。")
    final = buffer.value
    if final.startswith("\\\\?\\"):
        final = final[4:]
    if Path(final) != path:
        raise UnsafePath("文件最终路径与扫描路径不一致。")
    return {"volume": info.volume, "index": (info.index_high << 32) | info.index_low,
            "size": (info.size_high << 32) | info.size_low,
            "mtime": (info.modified.dwHighDateTime << 32) | info.modified.dwLowDateTime,
            "directory": bool(info.attributes & 0x10), "links": info.links}


def snapshot(path):
    no_reparse(path)
    with handle(path) as h:
        return info_from_handle(h, path)


def delete_verified(path_value, root_value, expected, root_identity, mode):
    root = validate_root(root_value, mode)
    path = canonical(path_value)
    if path == root or not under(path, root) or protected(path, root if mode == "cache" else None):
        raise UnsafePath("文件已超出允许清理的目录或受到保护。")
    no_reparse(path)
    with ExitStack() as stack:
        # Keep all ancestors stable until the file's delete disposition is set.
        for parent in reversed(path.parents):
            h = stack.enter_context(handle(parent, lock_directory=True))
            identity = info_from_handle(h, parent)
            if parent == root and any(identity[k] != root_identity[k] for k in ("volume", "index")):
                raise UnsafePath("扫描目录已经替换，请重新扫描。")
        h = stack.enter_context(handle(path, deleting=True))
        actual = info_from_handle(h, path)
        if actual != expected or actual["directory"] or actual["links"] != 1:
            raise UnsafePath("文件已经变化或存在硬链接，请重新扫描。")
        # FILE_DISPOSITION_INFO uses BOOLEAN (one byte), not the four-byte BOOL.
        disposition = ctypes.c_ubyte(1)
        if not _kernel().SetFileInformationByHandle(h, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            raise ctypes.WinError(ctypes.get_last_error())


def volumes():
    if not supported():
        return []
    k = _kernel()
    mask = k.GetLogicalDrives()
    result = []
    for i in range(26):
        root = f"{chr(65 + i)}:\\"
        if mask & (1 << i) and k.GetDriveTypeW(root) == 3:
            try:
                total, used, free = shutil.disk_usage(root)
                result.append({"path": root, "total": total, "used": used, "free": free})
            except OSError:
                continue
    return result
