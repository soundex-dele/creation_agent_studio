"""Read-only API for Skills installed in the active Agent Engine."""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .runtime_skills import (
    discover_runtime_skills,
    resolve_skill_adapter,
    skill_directory_for_adapter,
)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_runtime_skills(request):
    """Return a fresh scan of the currently configured adapter directory."""

    adapter = resolve_skill_adapter()
    directory = skill_directory_for_adapter(adapter)
    return Response({
        "adapter": adapter,
        "directory": str(directory),
        "exists": directory.is_dir(),
        "skills": discover_runtime_skills(adapter),
    })
