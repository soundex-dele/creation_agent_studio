"""Shared key setup checks; no connections to a real server."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import deploy_frontend
import deploy_ssh
import push_code


class DeploySshTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.key = self.directory / "ssh keys" / "deployment"
        stack.enter_context(patch.object(deploy_ssh, "default_identity", return_value=self.key))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def test_default_key_used_by_both_scripts_and_explicit_key_takes_priority(self):
        self.assertNotIn("-i", deploy_ssh.ssh_options())
        self.key.parent.mkdir()
        self.key.touch()
        for module in (deploy_frontend, push_code):
            options = module.ssh_options()
            self.assertEqual(options[options.index("-i") + 1], str(self.key))
        custom = self.directory / "custom key"
        custom.touch()
        self.assertIn(str(custom.resolve()), deploy_ssh.ssh_options(custom))
        with self.assertRaises(RuntimeError):
            deploy_ssh.ssh_options(self.directory / "missing")

    def test_setup_installs_public_key_and_verifies_without_password(self):
        with patch.object(deploy_ssh.shutil, "which", return_value="ssh-keygen"), \
             patch.object(deploy_ssh.subprocess, "check_output", return_value="ssh-ed25519 AAAA\n"), \
             patch.object(deploy_ssh.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            def execute(command, **kwargs):
                if command[0] == "ssh-keygen":
                    self.key.touch()
                return subprocess.CompletedProcess(command, 0)
            run.side_effect = execute
            deploy_ssh.setup_ssh("ssh", "user@host", 2222)
            generation, installation, verification = run.call_args_list
            self.assertIn("ed25519", generation.args[0])
            self.assertEqual(installation.kwargs["input"], b"ssh-ed25519 AAAA\n")
            self.assertIn("2222", installation.args[0])
            self.assertIn("NumberOfPasswordPrompts=1", installation.args[0])
            self.assertIn("BatchMode=yes", verification.args[0])
            run.reset_mock()
            deploy_ssh.setup_ssh("ssh", "user@host", 2222)
            self.assertEqual(run.call_count, 2)  # Existing private key is never regenerated.

    def test_dry_run_has_no_filesystem_or_process_side_effects(self):
        with patch.object(deploy_ssh.subprocess, "run") as run, \
             patch.object(deploy_ssh.subprocess, "check_output") as output:
            deploy_ssh.setup_ssh("ssh", "user@host", 22, dry_run=True)
        run.assert_not_called()
        output.assert_not_called()
        self.assertFalse(self.key.parent.exists())

    def test_setup_entry_points_skip_build_and_git_checks(self):
        for module in (deploy_frontend, push_code):
            with self.subTest(module=module.__name__), \
                 patch.object(module.shutil, "which", return_value="ssh"), \
                 patch.object(module, "setup_ssh") as setup, \
                 patch.object(module.subprocess, "run") as run, \
                 patch.object(module.subprocess, "check_output") as output:
                module.main(["--setup-ssh", "--port", "2222", "--dry-run"])
                setup.assert_called_once_with("ssh", module.REMOTE, 2222, None, dry_run=True)
                run.assert_not_called()
                output.assert_not_called()

    def test_failed_install_stops_and_failed_verification_is_reported(self):
        self.key.parent.mkdir()
        self.key.touch()
        with patch.object(deploy_ssh.shutil, "which", return_value="ssh-keygen"), \
             patch.object(deploy_ssh.subprocess, "check_output", return_value="ssh-ed25519 AAAA"), \
             patch.object(deploy_ssh.subprocess, "run") as run:
            run.side_effect = subprocess.CalledProcessError(255, "ssh")
            with self.assertRaises(subprocess.CalledProcessError):
                deploy_ssh.setup_ssh("ssh", "user@host", 22)
            self.assertEqual(run.call_count, 1)
            run.side_effect = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 255)]
            with self.assertRaisesRegex(RuntimeError, "免密验证失败"):
                deploy_ssh.setup_ssh("ssh", "user@host", 22)

    def test_install_preserves_existing_keys_and_is_idempotent(self):
        ssh_dir = self.directory / ".ssh"
        ssh_dir.mkdir()
        authorized = ssh_dir / "authorized_keys"
        authorized.write_text("ssh-ed25519 OLD", encoding="utf-8")
        environment = dict(os.environ, HOME=self.directory.as_posix())
        for _ in range(2):
            subprocess.run(
                ["sh", "-c", deploy_ssh.INSTALL_KEY], input=b"ssh-ed25519 NEW\n",
                env=environment, check=True,
            )
        self.assertEqual(authorized.read_text().splitlines(), ["ssh-ed25519 OLD", "ssh-ed25519 NEW"])


if __name__ == "__main__":
    unittest.main()
