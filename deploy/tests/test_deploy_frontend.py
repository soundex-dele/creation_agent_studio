"""Deployment checks without network access or a real build."""

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "deploy_frontend", Path(__file__).resolve().parents[2] / "deploy_frontend.py",
)
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


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
        deploy.main(["--port", "2222"])
        calls = self.child.call_args_list
        self.assertEqual(calls[0].args[0], ["npm", "run", "build"])
        self.assertEqual(calls[0].kwargs["cwd"], self.frontend)
        self.assertEqual(calls[1].args[0][-2:], [deploy.REMOTE, "mkdir -p -- /root/creation_agent_studio/frontend"])
        self.assertEqual(calls[2].args[0][-5:], ["-P", "2222", "-r", "dist", f"{deploy.REMOTE}:{deploy.REMOTE_DIR}/"])
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
        deploy.main(["--dry-run"])
        self.child.assert_not_called()

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
