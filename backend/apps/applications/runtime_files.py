"""User-scoped access to server-side runtime folders."""
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .runtime_paths import (
    resolve_runtime_path, visible_runtime_roots,
    runtime_path_is_accessible, runtime_parent,
)

VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".ts", ".m4v",
}


class FolderPathSerializer(serializers.Serializer):
    path = serializers.CharField(required=True, max_length=1024)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_runtime_directories(request):
    raw = (request.query_params.get("path") or "").strip()
    try:
        if not raw:
            roots = [{"name": root.name or str(root), "path": str(root)}
                     for root in visible_runtime_roots(request.user)]
            return Response({"path": "", "parent": "", "roots": roots, "dirs": []})
        path = resolve_runtime_path(raw, request.user)
        if not path.is_dir():
            return Response({"detail": "不是有效目录"}, status=status.HTTP_400_BAD_REQUEST)
        entries = sorted(path.iterdir(), key=lambda item: item.name)
        dirs = [{"name": item.name, "path": str(item)} for item in entries
                if runtime_path_is_accessible(item, request.user) and item.is_dir()]
        parent = runtime_parent(path, request.user)
    except PermissionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    return Response({"path": str(path), "parent": parent, "roots": [], "dirs": dirs})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def scan_runtime_folder(request):
    serializer = FolderPathSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        path = resolve_runtime_path(serializer.validated_data["path"], request.user)
        videos = []
        if path.is_dir():
            videos = [{"name": item.name, "path": str(item)}
                      for item in sorted(path.iterdir(), key=lambda item: item.name)
                      if runtime_path_is_accessible(item, request.user)
                      and item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS]
    except PermissionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    return Response({"folder": str(path), "videos": videos})
