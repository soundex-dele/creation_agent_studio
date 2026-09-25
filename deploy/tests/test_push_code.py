"""Exercise Git deployment against temporary repositories, without SSH."""

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "push_code", Path(__file__).resolve().parents[2] / "push_code.py",
)
push_code = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(push_code)
REAL_RUN = subprocess.run


class PushCodeTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        temporary = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.local = temporary / "local"
        self.remote = temporary / "remote checkout"
        self.local.mkdir()
        self.git("init", cwd=self.local)
        self.git("config", "user.name", "Deploy Test", cwd=self.local)
        self.git("config", "user.email", "deploy@example.invalid", cwd=self.local)
        self.git("config", "commit.gpgsign", "false", cwd=self.local)
        (self.local / "app.py").write_text("version = 1\n")
        self.git("add", "app.py", cwd=self.local)
        self.git("commit", "-m", "Initial", cwd=self.local)
        stack.enter_context(patch.object(push_code, "ROOT", self.local))
        stack.enter_context(patch.object(push_code, "REMOTE_DIR", str(self.remote)))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def git(self, *args, cwd):
        return REAL_RUN(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    def prepare(self, branch="main"):
        return REAL_RUN(
            ["sh", "-c", push_code.prepare_command(branch)],
            check=True, capture_output=True, text=True,
        )

    def push(self):
        return self.git("push", str(self.remote), "HEAD:refs/heads/main", cwd=self.local)

    def test_push_updates_checkout_and_preserves_runtime_files(self):
        self.prepare()
        (self.remote / ".env").write_text("SERVER_CONFIG=1\n")
        self.push()
        self.assertEqual((self.remote / "app.py").read_text(), "version = 1\n")
        (self.local / "app.py").write_text("version = 2\n")
        self.git("commit", "-am", "Update", cwd=self.local)
        self.push()
        self.assertEqual((self.remote / "app.py").read_text(), "version = 2\n")
        self.assertEqual((self.remote / ".env").read_text(), "SERVER_CONFIG=1\n")

    def test_server_edits_are_not_overwritten(self):
        self.prepare()
        self.push()
        (self.remote / "app.py").write_text("server changes\n")
        (self.local / "app.py").write_text("version = 2\n")
        self.git("commit", "-am", "Update", cwd=self.local)
        with self.assertRaises(subprocess.CalledProcessError):
            self.push()
        self.assertEqual((self.remote / "app.py").read_text(), "server changes\n")

    def test_non_fast_forward_push_is_rejected(self):
        self.prepare()
        self.push()
        (self.local / "app.py").write_text("rewritten history\n")
        self.git("commit", "-am", "Rewritten", "--amend", cwd=self.local)
        with self.assertRaises(subprocess.CalledProcessError):
            self.push()
        self.assertEqual((self.remote / "app.py").read_text(), "version = 1\n")

    def test_different_server_branch_is_rejected(self):
        self.prepare("production")
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare("main")
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD", cwd=self.remote).stdout.strip(), "production")

    def test_existing_untracked_source_is_preserved(self):
        self.prepare()
        (self.remote / "app.py").write_text("existing code\n")
        with self.assertRaises(subprocess.CalledProcessError):
            self.push()
        self.assertEqual((self.remote / "app.py").read_text(), "existing code\n")

    def test_dry_run_only_executes_local_git_checks(self):
        with patch.object(push_code.subprocess, "run", wraps=REAL_RUN) as child:
            push_code.main(["--dry-run"])
        for call in child.call_args_list:
            self.assertEqual(Path(call.args[0][0]).stem, "git")
            self.assertNotIn("push", call.args[0])
        self.assertFalse(self.remote.exists())

    def test_failed_push_stops_submodule_update(self):
        with patch.object(push_code, "run") as command:
            command.side_effect = [None, subprocess.CalledProcessError(1, "git push")]
            with self.assertRaises(subprocess.CalledProcessError):
                push_code.main([])
        self.assertEqual(command.call_count, 2)
        push = command.call_args_list[1]
        self.assertEqual(push.args[0][1], "push")
        self.assertTrue(push.args[0][-1].endswith(":refs/heads/main"))
        self.assertNotIn("--force", push.args[0])
        self.assertIn("GIT_SSH_COMMAND", push.kwargs["env"])


if __name__ == "__main__":
    unittest.main()
