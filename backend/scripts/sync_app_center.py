#!/usr/bin/env python
"""Validate, migrate, and synchronize bundled Application Center packages."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent.parent
MANAGE_PY = BACKEND_ROOT / "manage.py"


def run_manage(*arguments: str) -> None:
    command = [sys.executable, str(MANAGE_PY), *arguments]
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=BACKEND_ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Application Center manifests, apply Django migrations, "
            "and synchronize packages into the application catalog."
        )
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate manifests and migration files without changing the database.",
    )
    parser.add_argument(
        "--package",
        dest="package_id",
        help="Synchronize only this application package ID.",
    )
    parser.add_argument(
        "--organization",
        dest="organization_id",
        help="Synchronize only this organization UUID.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(f"Application Center root: {BACKEND_ROOT / 'app_center'}")
    print(f"Python: {sys.executable}")

    try:
        run_manage("validate_app_center")
        run_manage("makemigrations", "--check", "--dry-run")
        if args.validate_only:
            print("\nValidation completed; database was not changed.")
            return 0

        run_manage("migrate", "--noinput")
        sync_arguments = ["sync_app_center"]
        if args.package_id:
            sync_arguments.extend(("--package", args.package_id))
        if args.organization_id:
            sync_arguments.extend(("--organization", args.organization_id))
        run_manage(*sync_arguments)
        run_manage("list_app_center_status")
    except subprocess.CalledProcessError as exc:
        print(
            f"\nApplication Center synchronization failed with exit code "
            f"{exc.returncode}.",
            file=sys.stderr,
        )
        return exc.returncode or 1

    print("\nApplication Center synchronization completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
