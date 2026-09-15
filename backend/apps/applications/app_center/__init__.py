"""Discovery and installation support for bundled application packages."""

from .discovery import AppCenterError, DiscoveredPackage, discover_packages

__all__ = ["AppCenterError", "DiscoveredPackage", "discover_packages"]
