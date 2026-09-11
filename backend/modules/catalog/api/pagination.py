from rest_framework.pagination import CursorPagination


class ApplicationCursorPagination(CursorPagination):
    page_size = 50
    max_page_size = 200
    ordering = ("-created_at", "-id")


class ApplicationRevisionCursorPagination(CursorPagination):
    page_size = 50
    max_page_size = 200
    ordering = "-revision_no"
