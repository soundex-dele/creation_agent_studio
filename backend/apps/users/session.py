"""Browser session helpers for the HttpOnly JWT refresh cookie."""

from django.conf import settings


def refresh_cookie_name():
    return getattr(settings, "JWT_REFRESH_COOKIE_NAME", "creation_refresh")


def set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        refresh_cookie_name(),
        str(refresh_token),
        max_age=int(getattr(settings, "JWT_REFRESH_COOKIE_MAX_AGE", 7 * 24 * 3600)),
        path=getattr(settings, "JWT_REFRESH_COOKIE_PATH", "/api/v1/"),
        secure=bool(getattr(settings, "JWT_REFRESH_COOKIE_SECURE", not settings.DEBUG)),
        httponly=True,
        samesite=getattr(settings, "JWT_REFRESH_COOKIE_SAMESITE", "Strict"),
    )
    return response


def clear_refresh_cookie(response):
    response.delete_cookie(
        refresh_cookie_name(),
        path=getattr(settings, "JWT_REFRESH_COOKIE_PATH", "/api/v1/"),
        samesite=getattr(settings, "JWT_REFRESH_COOKIE_SAMESITE", "Strict"),
    )
    return response
