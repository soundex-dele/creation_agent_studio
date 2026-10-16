"""Read-only installer tests; no package manager or browser is actually run."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

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
        dtk_env = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for executable in (dtk_env / "Scripts/python.exe", dtk_env / "bin/python"):
            executable.parent.mkdir()
            executable.touch()
        self.stack.enter_context(patch.object(installer, "DTK_VENV", dtk_env))
        self.stack.enter_context(patch.object(installer.sys, "prefix", str(installer.ROOT / "backend/venv")))
        self.stack.enter_context(patch.object(installer.sys, "base_prefix", "/host-python"))
        self.stack.enter_context(patch.object(installer, "require_program", side_effect=lambda name: name))
        self.stack.enter_context(patch.object(installer, "npm_command", return_value=["node", "npm-cli.js"]))
        self.stack.enter_context(patch.object(installer.shutil, "which", side_effect=lambda name: name))
        self.stack.enter_context(patch.object(installer.subprocess, "check_output", return_value="v24.1.0"))
        self.run = self.stack.enter_context(patch.object(installer, "run"))
        self.idle_check = self.stack.enter_context(patch.object(installer, "ensure_windows_venv_idle"))

    def test_busy_venv_fails_before_any_installation(self):
        self.idle_check.side_effect = RuntimeError("virtual environment is in use")
        with self.assertRaisesRegex(RuntimeError, "virtual environment is in use"):
            installer.main([])
        self.run.assert_not_called()

    def test_dry_run_and_list_do_not_require_idle_venv(self):
        installer.main(["--dry-run"])
        installer.main(["--list-apps"])
        self.idle_check.assert_not_called()

    def commands(self):
        return [[str(value) for value in call.args[0]] for call in self.run.call_args_list]

    def test_default_installs_locked_web_png_animation_and_probes_browsers(self):
        installer.main(["--dry-run"])
        commands = self.commands()
        self.assertTrue(any(command[1:] == ["submodule", "update", "--init", "--recursive"] for command in commands))
        pip = [command for command in commands if command[1:3] == ["-m", "pip"]]
        self.assertEqual(len(pip), 5)
        self.assertTrue(all(command[0] == sys.executable for command in pip))
        self.assertTrue(pip[1][-1].endswith("production.txt"))
        npm_calls = [call for call in self.run.call_args_list if "ci" in call.args[0]]
        self.assertEqual([call.kwargs["cwd"] for call in npm_calls], [installer.ROOT / "frontend", installer.PNG, installer.ANIMATION, installer.WEB_FETCH])
        self.assertTrue(all("--include=dev" in call.args[0] for call in npm_calls))
        self.assertTrue(any(command[-2:] == ["install", "chromium"] for command in commands))
        self.assertTrue(any("p.screenshot()" in command[-1] for command in commands))
        self.assertEqual(commands[-2][-2:], ["run", "browser"])
        self.assertIn("openBrowser('chrome'", commands[-1][-1])
        self.assertTrue(all(call.kwargs["dry_run"] for call in self.run.call_args_list))
        self.assertTrue(any(command[-1].endswith("collector_source_checks.py") for command in commands))

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

    def test_submodule_failure_warns_and_continues_with_local_sources(self):
        def fail_git(command, **kwargs):
            if "submodule" in command:
                raise subprocess.CalledProcessError(128, command)

        self.run.side_effect = fail_git
        with contextlib.redirect_stderr(io.StringIO()) as errors, contextlib.redirect_stdout(io.StringIO()) as output:
            installer.main(["--app", "kitchen-assistant"])
        self.assertIn("Submodule update failed", errors.getvalue())
        self.assertIn("completed with submodule warnings", output.getvalue())
        self.assertIn("git submodule update --init --recursive", output.getvalue())
        self.assertTrue(any("ci" in command for command in self.commands()))

    def test_missing_git_warns_and_continues(self):
        def require(name):
            if name == "git":
                raise RuntimeError("git is missing from PATH")
            return name

        with patch.object(installer, "require_program", side_effect=require), contextlib.redirect_stderr(io.StringIO()) as errors:
            installer.main(["--app", "kitchen-assistant"])
        self.assertIn("Skipping submodule update", errors.getvalue())
        self.assertTrue(any("ci" in command for command in self.commands()))

    def test_missing_submodules_skip_dependent_steps_after_failed_or_skipped_fetch(self):
        missing = {
            installer.ROOT / "app_center/creation_master/react/package.json",
            installer.ROOT / "app_center/creation_master/requirements.txt",
            installer.ROOT / "teaching_data/README.md",
            installer.ROOT / "backend/third_party/Douyin_TikTok_Download_API/src/dtk/__init__.py",
        }
        is_file = Path.is_file

        def fail_git(command, **kwargs):
            if "submodule" in command:
                raise subprocess.CalledProcessError(128, command)

        for options in ([], ["--skip-submodules"]):
            with self.subTest(options=options), patch.object(installer.sys, "platform", "win32"), patch.object(
                Path, "is_file", lambda path: False if path in missing else is_file(path),
            ), contextlib.redirect_stderr(io.StringIO()) as errors:
                self.run.reset_mock()
                self.run.side_effect = fail_git
                installer.main(["--with-creation-master", *options])
                commands = self.commands()
                self.assertIn("Skipping Creation Master", errors.getvalue())
                self.assertIn("Skipping DTK", errors.getvalue())
                self.assertIn("teaching_data/README.md", errors.getvalue())
                self.assertFalse(any(command[-1].endswith("verify_source.py") for command in commands))
                self.assertFalse(any("--python" in command for command in commands))
                self.assertFalse(any("creation_master" in command[-1] for command in commands))
                self.assertTrue(any("ci" in command for command in commands))
                self.assertTrue(any("openBrowser('chrome'" in command[-1] for command in commands))

    def test_package_installation_failure_stops_remaining_commands(self):
        for failing in ("pip", "ci"):
            with self.subTest(failing=failing):
                self.run.reset_mock()

                def fail_package(command, **kwargs):
                    if failing in command:
                        raise subprocess.CalledProcessError(1, command)

                self.run.side_effect = fail_package
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.main(["--app", "kitchen-assistant"])
                self.assertIn(failing, self.commands()[-1])

    def test_existing_dtk_validation_failure_still_stops_installation(self):
        def fail_validation(command, **kwargs):
            if str(command[-1]).endswith("verify_source.py"):
                raise subprocess.CalledProcessError(1, command)

        self.run.side_effect = fail_validation
        with self.assertRaises(subprocess.CalledProcessError):
            installer.main(["--app", "douyin-benchmark"])
        self.assertTrue(self.commands()[-1][-1].endswith("verify_source.py"))

    def test_dry_run_never_invokes_subprocess_run(self):
        # Exercise the real command runner rather than the plan recorder.
        with patch.object(installer.subprocess, "run") as child:
            RUN_COMMAND(["npm", "ci"], dry_run=True)
            child.assert_not_called()

    def test_selecting_animation_installs_only_its_extra_runtime(self):
        installer.main(["--dry-run", "--app", "animation-studio"])
        npm_calls = [call for call in self.run.call_args_list if "ci" in call.args[0]]
        self.assertEqual([call.kwargs["cwd"] for call in npm_calls], [installer.ROOT / "frontend", installer.ANIMATION])
        self.assertFalse(any(call.kwargs.get("cwd") == installer.PNG for call in self.run.call_args_list))
        self.assertFalse(any("--python" in command for command in self.commands()))

    def test_selecting_douyin_installs_isolated_runtime_without_browsers(self):
        installer.main(["--dry-run", "--app", "douyin-benchmark"])
        commands = self.commands()
        self.assertTrue(any(command[-1].endswith("verify_source.py") for command in commands))
        self.assertTrue(any(command[-1].endswith("douyin_video_url.requirements.txt") and "--python" in command
                            for command in commands))
        self.assertTrue(any(command[-1].endswith("collector_source_checks.py") for command in commands))
        self.assertFalse(any(call.kwargs.get("cwd") in (installer.PNG, installer.ANIMATION)
                             for call in self.run.call_args_list))

    def test_douyin_checks_both_environments_are_idle(self):
        installer.main(["--app", "douyin-benchmark"])
        self.assertEqual(self.idle_check.call_count, 2)
        self.idle_check.assert_called_with(installer.DTK_VENV)

    def test_busy_dtk_fails_before_any_installation(self):
        self.idle_check.side_effect = [None, RuntimeError("DTK virtual environment is in use")]
        with self.assertRaisesRegex(RuntimeError, "DTK virtual environment is in use"):
            installer.main(["--app", "douyin-benchmark"])
        self.run.assert_not_called()

    def test_shared_only_app_does_not_require_media_tools_or_browsers(self):
        with patch.object(installer.shutil, "which", return_value=None):
            installer.main(["--dry-run", "--app", "kitchen-assistant"])
        self.assertFalse(any(call.kwargs.get("cwd") in (installer.PNG, installer.ANIMATION) for call in self.run.call_args_list))

    def test_repeated_comma_selections_deduplicate_runtime_installations(self):
        installer.main(["--dry-run", "--app", "animation-studio,html-to-png", "--app", "animation-studio"])
        npm_calls = [call for call in self.run.call_args_list if "ci" in call.args[0]]
        self.assertEqual([call.kwargs["cwd"] for call in npm_calls].count(installer.ANIMATION), 1)

    def test_unknown_app_fails_before_mutating_anything(self):
        with self.assertRaisesRegex(RuntimeError, "Unknown application"):
            installer.main(["--app", "animation-studo"])
        self.run.assert_not_called()

    def test_list_does_not_require_venv_node_git_or_system_packages(self):
        with patch.object(installer.sys, "prefix", "/host-python"), patch.object(
            installer, "require_program", side_effect=AssertionError("must not probe tools"),
        ), patch.object(installer.subprocess, "check_output", side_effect=AssertionError("must not launch tools")):
            installer.main(["--list-apps"])
        self.run.assert_not_called()

    def test_animation_linux_system_install_includes_chromium_libraries(self):
        with patch.object(installer.sys, "platform", "linux"), patch.object(installer, "system_commands", return_value=[]):
            installer.main(["--dry-run", "--app", "animation-studio", "--system-deps"])
        self.assertTrue(any(command[-3:] == ["install", "chromium", "--with-deps"] for command in self.commands()))

    def test_catalog_covers_every_bundled_application_and_known_runtimes(self):
        catalog = json.loads(installer.CATALOG.read_text(encoding="utf-8"))["applications"]
        # Manifest package IDs follow the same slug convention as their directories.
        manifests = (installer.ROOT / "app_center").glob("*/application.yaml")
        self.assertEqual(set(catalog), {path.parent.name.replace("_", "-") for path in manifests})
        for app in catalog.values():
            self.assertTrue(set(app["runtimes"]) <= {"ffmpeg", "png", "animation", "dtk", "web-fetch"})

    def test_web_fetch_installs_its_locked_engine_and_browser_only(self):
        installer.main(["--dry-run", "--app", "web-fetch"])
        folders = [call.kwargs["cwd"] for call in self.run.call_args_list if "ci" in call.args[0]]
        self.assertEqual(folders, [installer.ROOT / "frontend", installer.WEB_FETCH])
        self.assertTrue(any("Web fetch Chromium check passed" in command[-1] for command in self.commands()))
        self.assertFalse(any("openBrowser" in command[-1] for command in self.commands()))

    def test_web_fetch_rejects_node_20_before_installing(self):
        with patch.object(installer.subprocess, "check_output", return_value="v20.19.0"):
            with self.assertRaisesRegex(RuntimeError, "Web fetch requires"):
                installer.main(["--dry-run", "--app", "web-fetch"])
        self.run.assert_not_called()

    def test_full_dry_run_does_not_start_package_managers_or_browsers(self):
        with patch.object(installer, "run", RUN_COMMAND), patch.object(installer.subprocess, "run") as child:
            installer.main(["--dry-run", "--skip-submodules"])
        child.assert_not_called()


class DtkInstallTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.venv = root / ".venv-dtk"
        self.stack.enter_context(patch.object(installer, "DTK_VENV", self.venv))
        self.stack.enter_context(patch.object(installer.sys, "version_info", (3, 13, 7)))
        self.stack.enter_context(patch.object(installer.sys, "platform", "win32"))
        self.execute = Mock()

    def commands(self):
        return [[str(value) for value in call.args[0]] for call in self.execute.call_args_list]

    def test_new_environment_uses_compatible_project_python(self):
        installer.install_dtk(self.execute)
        commands = self.commands()
        self.assertIn([sys.executable, "-m", "venv", "--without-pip", str(self.venv)], commands)
        requirements = next(command for command in commands if "-r" in command)
        self.assertEqual(requirements[:5], [sys.executable, "-m", "pip", "--python",
                                            str(self.venv / "Scripts/python.exe")])
        self.assertFalse(self.venv.exists())  # Recording/dry-run does not create directories.

    def test_incompatible_project_python_provisions_313_with_uv(self):
        for version in ((3, 11, 9), (3, 14, 0)):
            with self.subTest(version=version), patch.object(installer.sys, "version_info", version):
                self.execute.reset_mock()
                installer.install_dtk(self.execute)
                commands = self.commands()
                self.assertIn([sys.executable, "-m", "pip", "install", "uv>=0.6,<1"], commands)
                self.assertIn([sys.executable, "-m", "uv", "venv", "--python", "3.13", str(self.venv)], commands)

    def test_existing_environment_is_reused_on_windows_and_posix(self):
        for platform, relative in (("win32", "Scripts/python.exe"), ("linux", "bin/python")):
            with self.subTest(platform=platform), patch.object(installer.sys, "platform", platform):
                python = self.venv / relative
                python.parent.mkdir(parents=True, exist_ok=True)
                python.touch()
                self.execute.reset_mock()
                installer.install_dtk(self.execute)
                commands = self.commands()
                self.assertFalse(any("venv" in command for command in commands))
                self.assertEqual(commands[1][0], str(python))
                self.assertIn("sys.prefix != sys.base_prefix", commands[1][-1])
                self.assertEqual(commands[-1][0], str(python))

    def test_incomplete_environment_is_not_overwritten(self):
        self.venv.mkdir()
        marker = self.venv / "keep.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(RuntimeError, "Incomplete DTK environment"):
            installer.install_dtk(self.execute)
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(self.execute.call_count, 1)  # Only source verification.

    def test_source_or_runtime_validation_failure_prevents_dtk_package_install(self):
        python = self.venv / "Scripts/python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
        for successful_checks in (0, 1):
            with self.subTest(successful_checks=successful_checks):
                self.execute.reset_mock()
                self.execute.side_effect = [None] * successful_checks + [subprocess.CalledProcessError(1, "check")]
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.install_dtk(self.execute)
                self.assertFalse(any("install" in command for command in self.commands()))


class WindowsVenvTests(unittest.TestCase):
    def check_processes(self, processes, venv=None):
        with patch.object(installer.sys, "platform", "win32"), patch.object(
            installer.subprocess, "check_output", return_value=json.dumps(processes),
        ), patch.object(installer.os, "getpid", return_value=10), patch.object(
            installer.os, "getppid", return_value=9,
        ):
            installer.ensure_windows_venv_idle(venv)

    def test_detects_busy_dtk_environment(self):
        venv = installer.ROOT / "backend/.venv-dtk"
        process = dict(ProcessId=20, ParentProcessId=1, ExecutablePath=None,
                       CommandLine=f'"{venv}/Scripts/python.exe" collector.py')
        with self.assertRaisesRegex(RuntimeError, "PID 20.*collector.py"):
            self.check_processes([process], venv)

    def test_detects_host_interpreter_child_using_venv_command_line(self):
        process = dict(ProcessId=20, ParentProcessId=19, ExecutablePath="C:/Python313/python.exe",
                       CommandLine=f'"{sys.prefix}/Scripts/python.exe" manage.py run_execution_coordinator')
        with self.assertRaisesRegex(RuntimeError, "PID 20.*run_execution_coordinator"):
            self.check_processes([process])

    def test_detects_venv_executable_without_command_line(self):
        with self.assertRaisesRegex(RuntimeError, "PID 20"):
            self.check_processes([dict(ProcessId=20, ParentProcessId=1,
                                       ExecutablePath=f"{sys.prefix}/Scripts/python.exe", CommandLine=None)])

    def test_ignores_installer_ancestors_and_other_environments(self):
        processes = [dict(ProcessId=pid, ParentProcessId=parent,
                          ExecutablePath=f"{sys.prefix}/Scripts/python.exe", CommandLine=None)
                     for pid, parent in [(10, 9), (9, 8), (8, 1)]]
        processes.append(dict(ProcessId=20, ParentProcessId=1,
                              ExecutablePath=f"{sys.prefix}-other/Scripts/python.exe", CommandLine=None))
        self.check_processes(processes)

    def test_non_windows_does_not_launch_powershell(self):
        with patch.object(installer.sys, "platform", "linux"), patch.object(installer.subprocess, "check_output") as query:
            installer.ensure_windows_venv_idle()
        query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
