from rest_framework.pagination import CursorPagination


class RunAttemptCursorPagination(CursorPagination):
    page_size = 100
    page_size_query_param = "limit"
    max_page_size = 500
    ordering = ("attempt_no", "id")


class RunArtifactCursorPagination(CursorPagination):
    page_size = 100
    page_size_query_param = "limit"
    max_page_size = 500
    ordering = ("created_at", "id")
