"""URL patterns contributed by trusted application packages."""

import importlib

from django.conf import settings

from .discovery import discover_packages


def application_urlpatterns():
    packages, _ = discover_packages(settings.APP_CENTER_ROOT, strict=False)
    patterns = []
    for package in packages:
        urlconf = package.manifest.spec.backend.urlconf
        if urlconf:
            patterns.extend(importlib.import_module(urlconf).urlpatterns)
    return patterns


urlpatterns = application_urlpatterns()
