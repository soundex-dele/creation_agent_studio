"""Platform PTYs. Imported by views for capability checks; never spawns on import."""
import importlib.util
import os
from pathlib import Path
import shutil
import signal


def default_shell():
    if os.name == 'nt':
        return shutil.which('pwsh') or shutil.which('powershell')
    import pwd
    shell = pwd.getpwuid(os.getuid()).pw_shell
    return shell if shell and os.path.isfile(shell) and os.access(shell, os.X_OK) else '/bin/sh'


def terminal_capability():
    shell = default_shell()
    available = importlib.util.find_spec('winpty' if os.name == 'nt' else 'ptyprocess') is not None
    if os.name != 'nt':
        available = available and importlib.util.find_spec('psutil') is not None
    return {'supported': bool(shell and available), 'shell': Path(shell).name if shell else '',
            'platform': os.name, 'max_sessions': 8}


class WindowsJob:
    """A per-terminal kill-on-close Job Object also contains descendants."""
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64),
                        ('Flags', w.DWORD), ('MinWorkingSet', ctypes.c_size_t),
                        ('MaxWorkingSet', ctypes.c_size_t), ('ActiveProcesses', w.DWORD),
                        ('Affinity', ctypes.c_size_t), ('Priority', w.DWORD), ('Scheduling', w.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOps', 'WriteOps', 'OtherOps',
                                                          'ReadBytes', 'WriteBytes', 'OtherBytes')]

        class Extended(ctypes.Structure):
            _fields_ = [('Basic', Basic), ('Io', Io), ('ProcessMemory', ctypes.c_size_t),
                        ('JobMemory', ctypes.c_size_t), ('PeakProcessMemory', ctypes.c_size_t),
                        ('PeakJobMemory', ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [w.LPVOID, w.LPCWSTR], w.HANDLE),
            ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
            ('OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
            ('CloseHandle', [w.HANDLE], w.BOOL),
        ):
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        process = None
        try:
            if not self.handle or not self.kernel.SetInformationJobObject(
                    self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            process = self.kernel.OpenProcess(0x100 | 0x1, False, pid)
            if not process or not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise
        finally:
            if process:
                self.kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class TerminalProcess:
    def __init__(self, cols, rows):
        shell = default_shell()
        env = dict(os.environ, TERM='xterm-256color', COLORTERM='truecolor')
        self.job = None
        if os.name == 'nt':
            from winpty import Backend, PtyProcess
            self.process = PtyProcess.spawn([shell, '-NoLogo'], cwd=str(Path.home()), env=env,
                                            dimensions=(rows, cols), backend=str(Backend.ConPTY))
            try:
                self.job = WindowsJob(self.process.pid)
            except BaseException:
                self.process.close(force=True)
                raise
        else:
            from ptyprocess import PtyProcessUnicode
            self.process = PtyProcessUnicode.spawn([shell, '-i'], cwd=str(Path.home()), env=env,
                                                   dimensions=(rows, cols))
        self.shell = Path(shell).name
        self.closed = False

    def read(self):
        return self.process.read(4096)

    def write(self, data):
        if os.name == 'nt':
            # ConPTY's write-all API can return 0 on success (pywinpty 3.0.5).
            # It raises on failure. Never retry based on this return value.
            self.process.write(data)
            return
        # Keep partial writes as bytes, including a split UTF-8 code point.
        remaining = data.encode('utf-8')
        while remaining:
            written = os.write(self.process.fd, remaining)
            if not written:
                raise OSError('Terminal input closed')
            remaining = remaining[written:]

    def resize(self, cols, rows):
        self.process.setwinsize(rows, cols)

    def exit_code(self):
        self.process.isalive()
        return self.process.exitstatus

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.job:
            self.job.close()
        elif os.name != 'nt':
            import psutil
            try:
                descendants = psutil.Process(self.process.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                descendants = []
            for child in reversed(descendants):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            # PTY foreground jobs have their own group (e.g. a running editor).
            groups = {self.process.pid}
            try:
                groups.add(os.tcgetpgrp(self.process.fd))
            except OSError:
                pass
            for group in groups:
                if group > 0 and group != os.getpgrp():
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        try:
            self.process.close(force=True)
        except (OSError, EOFError):
            pass
