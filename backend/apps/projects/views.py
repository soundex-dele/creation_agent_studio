from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from django.db.models import Q
from .models import Project, ProjectAsset
from .serializers import ProjectListSerializer, ProjectDetailSerializer, CreateProjectSerializer, ProjectAssetSerializer
from .services.workspace_files import (
    WorkspaceFileError, list_workspace_files, read_workspace_file)

class ProjectViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        from apps.enterprise.permissions import resolve_organization
        organization = resolve_organization(self.request)
        return Project.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            user=self.request.user,
        ).select_related('application', 'workflow').prefetch_related('conversations')

    def get_serializer_class(self):
        if self.action == 'list':
            return ProjectListSerializer
        if self.action == 'create':
            return CreateProjectSerializer
        return ProjectDetailSerializer

    def create(self, request, *args, **kwargs):
        # Validate and persist, then return the complete project representation.
        from apps.enterprise.permissions import resolve_organization
        resolve_organization(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        detail = ProjectDetailSerializer(serializer.instance, context={'request': request})
        return Response(detail.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def recent(self, request):
        projects = self.get_queryset()[:5]
        serializer = ProjectListSerializer(projects, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='workspace-files')
    def workspace_files(self, request, pk=None):
        project = self.get_object()
        relative_path = request.query_params.get('path')
        try:
            if relative_path is not None:
                return Response(read_workspace_file(project, relative_path))
            return Response(list_workspace_files(project))
        except WorkspaceFileError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except FileNotFoundError:
            return Response(
                {'detail': '文件不存在或已被删除。'},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=['post', 'delete'])
    def assets(self, request, pk=None):
        project = self.get_object()
        if request.method == 'POST':
            serializer = ProjectAssetSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(project=project)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        asset_id = request.data.get('asset_id')
        try:
            asset = project.assets.get(id=asset_id)
            asset.delete()
            return Response({'detail': 'Resource deleted'}, status=status.HTTP_204_NO_CONTENT)
        except ProjectAsset.DoesNotExist:
            return Response({'detail': 'Resource not found'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], url_path='upload')
    def upload(self, request, pk=None):
        project = self.get_object()
        uploaded = request.FILES.get('file')
        if uploaded is None:
            return Response({'file': 'This field is required.'}, status=400)
        max_bytes = 1024 * 1024 * 1024
        if uploaded.size > max_bytes:
            return Response({'file': 'File exceeds the 1 GiB limit.'}, status=413)
        extension = uploaded.name.rsplit('.', 1)[-1].lower() if '.' in uploaded.name else ''
        allowed = {'mp4', 'mov', 'mkv', 'mp3', 'wav', 'png', 'jpg', 'jpeg',
                   'webp', 'txt', 'md', 'pdf', 'srt'}
        if extension not in allowed:
            return Response({'file': 'File type is not allowed.'}, status=415)
        asset_type = request.data.get('asset_type', 'other')
        asset = ProjectAsset.objects.create(
            project=project, asset_type=asset_type, name=uploaded.name,
            file=uploaded, metadata={'content_type': uploaded.content_type,
                                     'size': uploaded.size})
        return Response(ProjectAssetSerializer(asset).data, status=201)
