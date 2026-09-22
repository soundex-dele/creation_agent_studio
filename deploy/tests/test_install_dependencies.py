"""Read-only installer tests; no package manager or browser is actually run."""

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "install_dependencies", Path(__file__).resolve().parents[1] / "install_dependencies.py",
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)
RUN_COMMAND = installer.run


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(installer.sys, "prefix", str(installer.ROOT / "backend/venv")))
        self.stack.enter_context(patch.object(installer.sys, "base_prefix", "/host-python"))
        self.stack.enter_context(patch.object(installer, "require_program", side_effect=lambda name: name))
        self.stack.enter_context(patch.object(installer, "npm_command", return_value=["node", "npm-cli.js"]))
        self.stack.enter_context(patch.object(installer.shutil, "which", side_effect=lambda name: name))
        self.stack.enter_context(patch.object(installer.subprocess, "check_output", return_value="v24.1.0"))
        self.run = self.stack.enter_context(patch.object(installer, "run"))

    def commands(self):
        return [[str(value) for value in call.args[0]] for call in self.run.call_args_list]

    def test_default_installs_locked_web_and_png_packages_and_probes_chromium(self):
        installer.main(["--dry-run"])
        commands = self.commands()
        self.assertTrue(any(command[1:] == ["submodule", "update", "--init", "--recursive"] for command in commands))
        pip = [command for command in commands if command[1:3] == ["-m", "pip"]]
        self.assertEqual(len(pip), 3)
        self.assertTrue(all(command[0] == sys.executable for command in pip))
        self.assertTrue(pip[1][-1].endswith("production.txt"))
        npm_calls = [call for call in self.run.call_args_list if "ci" in call.args[0]]
        self.assertEqual([call.kwargs["cwd"] for call in npm_calls], [installer.ROOT / "frontend", installer.PNG])
        self.assertTrue(all("--include=dev" in call.args[0] for call in npm_calls))
        self.assertEqual(commands[-2][-2:], ["install", "chromium"])
        self.assertIn("p.screenshot()", commands[-1][-1])
        self.assertTrue(all(call.kwargs["dry_run"] for call in self.run.call_args_list))

    def test_optional_packages_are_explicit_and_use_project_python(self):
        with patch.object(installer.sys, "platform", "win32"):
            installer.main(["--dry-run", "--skip-submodules", "--development", "--with-mobile",
                            "--with-creation-master", "--with-codex"])
        commands = self.commands()
        self.assertFalse(any("submodule" in command for command in commands))
        self.assertTrue(any(command[-1].endswith("development.txt") for command in commands))
        self.assertTrue(any(command[-1].endswith("creation_master\\requirements.txt")
                            or command[-1].endswith("creation_master/requirements.txt") for command in commands))
        self.assertTrue(any(call.kwargs.get("cwd") == installer.ROOT / "mobile" for call in self.run.call_args_list))
        self.assertIn([sys.executable, "-m", "playwright", "install", "chromium"], commands)
        self.assertTrue(any(f"@openai/codex@{installer.CODEX_VERSION}" in command for command in commands))

    def test_missing_ffmpeg_fails_before_installing_anything(self):
        with patch.object(installer.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "FFmpeg/ffprobe"):
                installer.main(["--dry-run"])
        self.run.assert_not_called()

    def test_refuses_host_interpreter_and_incompatible_node(self):
        with patch.object(installer.sys, "prefix", "/host-python"):
            with self.assertRaisesRegex(RuntimeError, "virtual environment"):
                installer.main([])
        with patch.object(installer.subprocess, "check_output", return_value="v22.1.0"):
            with self.assertRaisesRegex(RuntimeError, "unsupported"):
                installer.main([])
        self.run.assert_not_called()

    def test_linux_browser_install_includes_system_libraries(self):
        with patch.object(installer.sys, "platform", "linux"), patch.object(
            installer, "system_commands", return_value=[["sudo", "apt-get", "install", "ffmpeg"]],
        ):
            installer.main(["--dry-run", "--system-deps"])
        commands = self.commands()
        self.assertEqual(commands[0], ["sudo", "apt-get", "install", "ffmpeg"])
        self.assertTrue(any(command[-3:] == ["install", "chromium", "--with-deps"] for command in commands))

    def test_installation_failure_stops_remaining_commands(self):
        self.run.side_effect = subprocess.CalledProcessError(1, "git")
        with self.assertRaises(subprocess.CalledProcessError):
            installer.main([])
        self.assertEqual(self.run.call_count, 1)

    def test_dry_run_never_invokes_subprocess_run(self):
        # Exercise the real command runner rather than the plan recorder.
        with patch.object(installer.subprocess, "run") as child:
            RUN_COMMAND(["npm", "ci"], dry_run=True)
            child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
