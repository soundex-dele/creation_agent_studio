"""Exercise launcher preflight in temporary checkouts; never start real services."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
# Prefer Git Bash over the Windows WSL launcher.
SH = shutil.which("sh")
BASH = str(Path(SH).with_name("bash.exe")) if os.name == "nt" and SH else shutil.which("bash")
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="deploy launcher ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("deploy.sh", "deploy.ps1"):
            shutil.copyfile(ROOT / name, self.root / name)
        for relative in ("backend/venv/bin/python", "backend/venv/Scripts/python.exe",
                         "frontend/node_modules/vite/bin/vite.js"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/bin/sh\nexit 99\n")
            path.chmod(0o755)
        self.env = dict(os.environ)
        self.env.pop("FRONTEND_MODE", None)
        self.env.update(BACKEND_PORT="8080", FRONTEND_PORT="3030")

    def preview_output(self):
        output = self.root / "frontend/dist/index.html"
        output.parent.mkdir()
        output.write_text("existing build")

    def run_launcher(self, shell, arguments=(), mode=None):
        env = dict(self.env)
        if mode is not None:
            env["FRONTEND_MODE"] = mode
        if shell == "bash":
            command = [BASH, "deploy.sh", "--dry-run", *arguments]
        else:
            command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                       "deploy.ps1", "-DryRun", *arguments]
        result = subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
        return result.returncode, result.stdout + result.stderr

    def check_modes(self, shell, flag):
        code, output = self.run_launcher(shell)
        self.assertEqual(code, 0, output)
        self.assertIn("Frontend mode: dev (no build)", output)
        self.preview_output()
        for arguments, mode, expected in (([flag, "preview"], None, "preview"),
                                           ([], "preview", "preview"),
                                           ([flag, "dev"], "preview", "dev"),
                                           ([flag, "preview"], "invalid", "preview")):
            with self.subTest(shell=shell, arguments=arguments, mode=mode):
                code, output = self.run_launcher(shell, arguments, mode)
                self.assertEqual(code, 0, output)
                self.assertIn(f"Frontend mode: {expected} (no build)", output)
        self.assertEqual((self.root / "frontend/dist/index.html").read_text(), "existing build")
        self.assertFalse((self.root / "backend/logs").exists())

    def check_errors(self, shell, flag):
        for arguments, mode, message in (([flag, "preview"], None, "requires frontend"),
                                          ([flag, "invalid"], None, "invalid"),
                                          ([], "invalid", "invalid"),
                                          ([flag], None, "frontend")):
            with self.subTest(shell=shell, arguments=arguments, mode=mode):
                code, output = self.run_launcher(shell, arguments, mode)
                self.assertNotEqual(code, 0, output)
                self.assertIn(message, output.lower())
        self.assertFalse((self.root / "backend/logs").exists())

    @unittest.skipUnless(BASH and Path(BASH).is_file(), "Bash unavailable")
    def test_bash_modes_and_precedence(self):
        self.check_modes("bash", "--frontend-mode")
        code, output = self.run_launcher("bash", ["--frontend-mode=preview"])
        self.assertEqual(code, 0, output)
        self.assertIn("Frontend mode: preview", output)

    @unittest.skipUnless(BASH and Path(BASH).is_file(), "Bash unavailable")
    def test_bash_invalid_mode_and_missing_build(self):
        self.check_errors("bash", "--frontend-mode")

    @unittest.skipUnless(POWERSHELL and os.name == "nt", "Windows PowerShell unavailable")
    def test_powershell_modes_and_precedence(self):
        self.check_modes("powershell", "-FrontendMode")

    @unittest.skipUnless(POWERSHELL and os.name == "nt", "Windows PowerShell unavailable")
    def test_powershell_invalid_mode_and_missing_build(self):
        self.check_errors("powershell", "-FrontendMode")


if __name__ == "__main__":
    unittest.main()
