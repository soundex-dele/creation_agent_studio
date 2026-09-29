"""Verify the deployed source checkout against provider-lock.json; no network calls."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[4]
lock = json.loads(Path(__file__).with_name("provider-lock.json").read_text())
source = root / lock["source_path"]
commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
changed = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
if commit != lock["commit"] or changed:
    raise SystemExit("DTK source does not match the pinned clean checkout.")
print(f"DTK {lock['version']} source verified: {commit}")
