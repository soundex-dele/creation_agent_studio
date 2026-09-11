from rest_framework.response import Response
from rest_framework.views import APIView


class ProblemDetailsAPIView(APIView):
    """Render DRF authentication and permission failures as problem details."""

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        field_errors = response.data if isinstance(response.data, dict) and detail is None else None
        code = getattr(detail, "code", None) or getattr(exc, "default_code", "api_error")
        if field_errors is not None:
            code = "invalid_request"
        title = str(code).replace("_", " ").capitalize()
        body = {
            "type": f"urn:creation-agent-studio:problem:{code}",
            "code": str(code),
            "title": title,
            "status": response.status_code,
            "detail": str(detail or "Request validation failed."),
            "request_id": getattr(self.request, "request_id", ""),
        }
        if field_errors is not None:
            body["errors"] = field_errors
        return Response(
            body,
            status=response.status_code,
            headers=response.headers,
            content_type="application/problem+json",
        )
