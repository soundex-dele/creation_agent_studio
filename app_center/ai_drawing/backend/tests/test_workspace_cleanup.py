import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app_center.ai_drawing.runtime import _attempt_workspace, _cleanup_workspace


def locked_error():
    error = PermissionError("The process cannot access the file because it is being used by another process")
    error.winerror = 32
    return error


def test_cleanup_retries_transient_lock(tmp_path):
    root = tmp_path.resolve()
    workspace = root / "attempt-test"
    workspace.mkdir()
    original_rmtree = shutil.rmtree
    calls = []

    def remove(path):
        calls.append(path)
        if len(calls) == 1:
            raise locked_error()
        original_rmtree(path)

    with patch("app_center.ai_drawing.runtime.shutil.rmtree", side_effect=remove), patch("app_center.ai_drawing.runtime.time.sleep") as sleep:
        _cleanup_workspace(workspace, root)
    assert len(calls) == 2
    sleep.assert_called_once_with(0.1)
    assert not workspace.exists()


@pytest.mark.parametrize("body_error", [None, RuntimeError("original generation failure"), TimeoutError("original timeout")])
def test_persistent_lock_never_replaces_result_or_original_error(tmp_path, caplog, body_error):
    def work():
        with _attempt_workspace(tmp_path) as directory:
            Path(directory, "result.png").write_bytes(b"already archived")
            if body_error:
                raise body_error
            return "generated"

    with patch("app_center.ai_drawing.runtime.shutil.rmtree", side_effect=locked_error()) as remove, patch("app_center.ai_drawing.runtime.time.sleep"):
        if body_error:
            with pytest.raises(type(body_error)) as caught:
                work()
            assert caught.value is body_error
        else:
            assert work() == "generated"
    assert remove.call_count == 3
    assert len(list(tmp_path.glob("attempt-*/result.png"))) == 1
    assert "workspace retained" in caplog.text


def test_cleanup_cannot_delete_root_or_unrelated_directory(tmp_path):
    root = (tmp_path / "drawing").resolve()
    root.mkdir()
    outside = (tmp_path / "unrelated").resolve()
    outside.mkdir()
    with patch("app_center.ai_drawing.runtime.shutil.rmtree") as remove:
        _cleanup_workspace(root, root)
        _cleanup_workspace(outside, root)
    remove.assert_not_called()
    assert root.exists() and outside.exists()


def test_normal_workspace_is_removed(tmp_path):
    with _attempt_workspace(tmp_path) as workspace:
        Path(workspace, "reference.png").write_bytes(b"reference")
    assert not Path(workspace).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows locks a process's current directory")
def test_real_windows_child_cwd_lock_preserves_original_error(tmp_path, caplog):
    child = None
    try:
        with pytest.raises(RuntimeError, match="original generation failure"):
            with _attempt_workspace(tmp_path) as workspace:
                child = subprocess.Popen(
                    [sys.executable, "-c", "import sys; print('ready', flush=True); sys.stdin.read()"],
                    cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    text=True, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                assert child.stdout.readline().strip() == "ready"
                raise RuntimeError("original generation failure")
        assert Path(workspace).is_dir()
        assert "workspace retained" in caplog.text
    finally:
        if child:
            child.communicate(timeout=10)
        if 'workspace' in locals():
            _cleanup_workspace(Path(workspace), tmp_path.resolve())
    assert not Path(workspace).exists()
