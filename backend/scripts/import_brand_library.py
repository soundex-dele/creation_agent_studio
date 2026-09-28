#!/usr/bin/env python
"""Run the brand import command with the current project's Django configuration."""

import os
from pathlib import Path
import sys


def main():
    backend_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(backend_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.development")
    from django.core.management import execute_from_command_line

    execute_from_command_line([str(backend_root / "manage.py"), "import_brand_library", *sys.argv[1:]])


if __name__ == "__main__":
    main()
