"""Tenant-authenticated access to server-side runtime folders."""
from pathlib import Path

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .runtime_paths import resolve_runtime_path, visible_runtime_roots


VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".ts", ".m4v",
}


class FolderPathSerializer(serializers.Serializer):
    path = serializers.CharField(required=True, max_length=1024)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_runtime_directories(request):
    raw = (request.query_params.get("path") or "").strip()
    if not raw:
        roots = [
            {"name": root.name or str(root), "path": str(root)}
            for root in visible_runtime_roots()
        ]
        return Response({"path": "", "parent": "", "roots": roots, "dirs": []})
    try:
        path = resolve_runtime_path(raw)
    except PermissionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if not path.is_dir():
        return Response({"detail": "不是有效目录"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        entries = sorted(path.iterdir(), key=lambda item: item.name)
    except PermissionError:
        return Response({"detail": "无权限访问该目录"}, status=status.HTTP_403_FORBIDDEN)
    dirs = [{"name": item.name, "path": str(item)} for item in entries if item.is_dir()]
    parent = path.parent
    parent_value = "" if parent == path else str(parent)
    return Response({"path": str(path), "parent": parent_value, "roots": [], "dirs": dirs})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def scan_runtime_folder(request):
    serializer = FolderPathSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        path = resolve_runtime_path(serializer.validated_data["path"])
    except PermissionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    videos = []
    if path.is_dir():
        videos = [
            {"name": item.name, "path": str(item)}
            for item in sorted(path.iterdir(), key=lambda item: item.name)
            if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
        ]
    return Response({"folder": str(path), "videos": videos})
