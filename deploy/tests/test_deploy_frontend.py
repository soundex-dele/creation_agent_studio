"""Deployment checks without network access or a real build."""

import contextlib
import importlib.util
import io
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "deploy_frontend", Path(__file__).resolve().parents[2] / "deploy_frontend.py",
)
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)
REAL_RUN = subprocess.run


class DeployFrontendTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.frontend = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (self.frontend / "package.json").write_text("{}")
        stack.enter_context(patch.object(deploy, "FRONTEND", self.frontend))
        stack.enter_context(patch.object(deploy.shutil, "which", side_effect=lambda name: name))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.child = stack.enter_context(patch.object(deploy.subprocess, "run"))

    def test_build_precedes_upload_and_preserves_dist_directory(self):
        (self.frontend / "dist").mkdir()
        (self.frontend / "dist/index.html").write_text("built")
        (self.frontend / "dist/assets").mkdir()
        (self.frontend / "dist/assets/app.js").write_text("console.log('ok')")
        remote_dir = self.frontend / "remote frontend"

        def execute(command, **kwargs):
            if command[0] == "ssh":
                return REAL_RUN(["sh", "-c", command[-1]], check=True)
            if command[0] == "scp":
                archive = Path(command[-2])
                self.assertEqual(archive.read_bytes()[:2], b"\x1f\x8b")
                with tarfile.open(archive, "r:gz") as bundle:
                    self.assertIn("dist/index.html", bundle.getnames())
                    self.assertIn("dist/assets/app.js", bundle.getnames())
                shutil.copyfile(archive, command[-1].removeprefix(f"{deploy.REMOTE}:"))

        self.child.side_effect = execute
        with patch.object(deploy, "REMOTE_DIR", str(remote_dir)):
            deploy.main(["--port", "2222"])
        calls = self.child.call_args_list
        self.assertEqual(calls[0].args[0], ["npm", "run", "build"])
        self.assertEqual(calls[0].kwargs["cwd"], self.frontend)
        self.assertEqual(calls[1].args[0][-2:], [deploy.REMOTE, f"mkdir -p -- {shlex.quote(str(remote_dir))}"])
        self.assertEqual(calls[2].args[0][-4:-2], ["-P", "2222"])
        self.assertEqual((remote_dir / "dist/index.html").read_text(), "built")
        self.assertEqual((remote_dir / "dist/assets/app.js").read_text(), "console.log('ok')")
        self.assertFalse(Path(calls[2].args[0][-2]).exists())
        self.assertEqual(list(remote_dir.glob("*.tar.gz")), [])
        self.assertTrue(all(call.kwargs["check"] for call in calls))

    def test_build_failure_never_connects_to_server(self):
        self.child.side_effect = subprocess.CalledProcessError(1, "npm")
        with self.assertRaises(subprocess.CalledProcessError):
            deploy.main([])
        self.assertEqual(self.child.call_count, 1)

    def test_missing_output_never_connects_to_server(self):
        with self.assertRaisesRegex(RuntimeError, "index.html"):
            deploy.main([])
        self.assertEqual(self.child.call_count, 1)

    def test_dry_run_does_not_build_or_connect(self):
        with patch.object(deploy.tarfile, "open") as archive:
            deploy.main(["--dry-run"])
            archive.assert_not_called()
        self.child.assert_not_called()

    def test_upload_failure_never_extracts_and_removes_local_archive(self):
        (self.frontend / "dist").mkdir()
        (self.frontend / "dist/index.html").write_text("built")
        self.child.side_effect = [None, None, subprocess.CalledProcessError(1, "scp")]
        with self.assertRaises(subprocess.CalledProcessError):
            deploy.main([])
        self.assertEqual(self.child.call_count, 3)
        self.assertFalse(Path(self.child.call_args_list[2].args[0][-2]).exists())

    def test_extraction_failure_is_reported_and_removes_local_archive(self):
        (self.frontend / "dist").mkdir()
        (self.frontend / "dist/index.html").write_text("built")
        self.child.side_effect = [None, None, None, subprocess.CalledProcessError(2, "tar")]
        with self.assertRaises(subprocess.CalledProcessError):
            deploy.main([])
        self.assertEqual(self.child.call_count, 4)
        self.assertFalse(Path(self.child.call_args_list[2].args[0][-2]).exists())

    def test_ssh_failure_stops_before_scp_and_key_is_passed(self):
        (self.frontend / "dist").mkdir()
        (self.frontend / "dist/index.html").write_text("built")
        key = self.frontend / "test key"
        key.touch()
        self.child.side_effect = [None, subprocess.CalledProcessError(255, "ssh")]
        with self.assertRaises(subprocess.CalledProcessError):
            deploy.main(["-i", str(key)])
        self.assertEqual(self.child.call_count, 2)
        ssh_command = self.child.call_args_list[1].args[0]
        self.assertEqual(ssh_command[ssh_command.index("-i") + 1], str(key.resolve()))


if __name__ == "__main__":
    unittest.main()
