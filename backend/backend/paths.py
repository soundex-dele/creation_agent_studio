"""Source and frozen application locations, independent of the working directory."""
import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))


def expose_app_center(root=None):
    application_root = Path(root or os.environ.get("APP_CENTER_ROOT") or BUNDLE_ROOT / "app_center")
    if not application_root.is_absolute():
        application_root = BUNDLE_ROOT / application_root
    application_root = application_root.resolve()
    parent = str(application_root.parent)
    if parent in sys.path:
        sys.path.remove(parent)
    sys.path.insert(0, parent)
    return application_root
