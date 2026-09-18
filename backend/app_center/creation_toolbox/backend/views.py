from __future__ import annotations

import mimetypes
from pathlib import Path

from django.db import IntegrityError, transaction
from django.db.models import Count, Max
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.tenancy.permissions import HasPathOrganizationRole

from .models import (
    Copywriting,
    CreationProject,
    CreationWorkspace,
    MaterialFolder,
    MediaAsset,
    Recording,
    Scene,
    Script,
)
from .serializers import (
    AssetSerializer,
    CopywritingSerializer,
    FolderSerializer,
    GenerateCopywritingSerializer,
    ProjectSerializer,
    RecordingSerializer,
    SceneSerializer,
    ScriptSerializer,
    WorkspaceSerializer,
)
from .services import generate_copywriting, transcribe_audio


def _workspace(organization_id, application_id):
    return CreationWorkspace.objects.for_organization(organization_id).filter(
        application_id=application_id,
        application__organization_id=organization_id,
        application__is_active=True,
    ).first()


def _project(workspace, project_id):
    if workspace is None:
        return None
    return workspace.projects.filter(id=project_id).first()


def _project_for_input(workspace, project_id):
    if not project_id:
        return None
    return _project(workspace, project_id)


def _not_found(label):
    return Response({"detail": f"{label}不存在。"}, status=status.HTTP_404_NOT_FOUND)


def _asset_kind(mime_type: str, filename: str) -> str:
    mime = (mime_type or mimetypes.guess_type(filename)[0] or "").lower()
    if mime.startswith("image/"):
        return MediaAsset.Kind.IMAGE
    if mime.startswith("video/"):
        return MediaAsset.Kind.VIDEO
    if mime.startswith("audio/"):
        return MediaAsset.Kind.AUDIO
    if mime.startswith("text/") or mime in {"application/pdf", "application/json"}:
        return MediaAsset.Kind.DOCUMENT
    return MediaAsset.Kind.OTHER


class WorkspaceView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        workspace.project_count = workspace.projects.count()
        workspace.asset_count = MediaAsset.objects.filter(project__workspace=workspace).count()
        workspace.recording_count = workspace.recordings.count()
        workspace.copywriting_count = workspace.copywritings.count()
        workspace.script_count = workspace.scripts.count()
        return Response(WorkspaceSerializer(workspace).data)

    def patch(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        serializer = WorkspaceSerializer(workspace, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ProjectListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        projects = workspace.projects.annotate(
            asset_count=Count("assets", distinct=True),
            recording_count=Count("recordings", distinct=True),
            script_count=Count("scripts", distinct=True),
        )
        return Response(ProjectSerializer(projects, many=True).data)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        serializer = ProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(
                organization=request.organization,
                workspace=workspace,
                created_by=request.user,
            )
        except IntegrityError:
            return Response({"name": "同名工程已经存在。"}, status=400)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def patch(self, request, organization_id, application_id, project_id):
        workspace = _workspace(organization_id, application_id)
        project = _project(workspace, project_id)
        if project is None:
            return _not_found("工程")
        serializer = ProjectSerializer(project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except IntegrityError:
            return Response({"name": "同名工程已经存在。"}, status=400)
        return Response(serializer.data)

    def delete(self, request, organization_id, application_id, project_id):
        workspace = _workspace(organization_id, application_id)
        project = _project(workspace, project_id)
        if project is None:
            return _not_found("工程")
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FolderListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id, project_id):
        project = _project(_workspace(organization_id, application_id), project_id)
        if project is None:
            return _not_found("工程")
        parent_id = request.query_params.get("parent") or None
        folders = project.folders.filter(parent_id=parent_id).annotate(
            item_count=Count("assets", distinct=True) + Count("children", distinct=True)
        )
        return Response(FolderSerializer(folders, many=True).data)

    def post(self, request, organization_id, application_id, project_id):
        project = _project(_workspace(organization_id, application_id), project_id)
        if project is None:
            return _not_found("工程")
        parent = None
        parent_id = request.data.get("parent_id")
        if parent_id:
            parent = project.folders.filter(id=parent_id).first()
            if parent is None:
                return Response({"parent_id": "上级文件夹不存在。"}, status=400)
        serializer = FolderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if project.folders.filter(parent=parent, name=serializer.validated_data["name"]).exists():
            return Response({"name": "同名文件夹已经存在。"}, status=400)
        serializer.save(
            organization=request.organization,
            project=project,
            parent=parent,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class FolderDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def delete(self, request, organization_id, application_id, project_id, folder_id):
        project = _project(_workspace(organization_id, application_id), project_id)
        folder = project and project.folders.filter(id=folder_id).first()
        if folder is None:
            return _not_found("文件夹")
        folder.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssetListView(APIView):
    permission_classes = (HasPathOrganizationRole,)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request, organization_id, application_id, project_id):
        project = _project(_workspace(organization_id, application_id), project_id)
        if project is None:
            return _not_found("工程")
        folder_id = request.query_params.get("folder") or None
        assets = project.assets.filter(folder_id=folder_id)
        return Response(AssetSerializer(assets, many=True).data)

    def post(self, request, organization_id, application_id, project_id):
        project = _project(_workspace(organization_id, application_id), project_id)
        if project is None:
            return _not_found("工程")
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response({"file": "请选择要上传的文件。"}, status=400)
        folder = None
        folder_id = request.data.get("folder_id")
        if folder_id:
            folder = project.folders.filter(id=folder_id).first()
            if folder is None:
                return Response({"folder_id": "文件夹不存在。"}, status=400)
        name = Path(request.data.get("name") or uploaded.name).name[:255]
        mime_type = uploaded.content_type or mimetypes.guess_type(name)[0] or ""
        asset = MediaAsset.objects.create(
            organization=request.organization,
            project=project,
            folder=folder,
            name=name,
            file=uploaded,
            kind=_asset_kind(mime_type, name),
            mime_type=mime_type,
            size=uploaded.size,
            created_by=request.user,
        )
        return Response(AssetSerializer(asset).data, status=status.HTTP_201_CREATED)


class AssetDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def delete(self, request, organization_id, application_id, project_id, asset_id):
        project = _project(_workspace(organization_id, application_id), project_id)
        asset = project and project.assets.filter(id=asset_id).first()
        if asset is None:
            return _not_found("素材")
        asset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RecordingListView(APIView):
    permission_classes = (HasPathOrganizationRole,)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        recordings = workspace.recordings.select_related("project")
        project_id = request.query_params.get("project")
        if project_id:
            recordings = recordings.filter(project_id=project_id)
        return Response(RecordingSerializer(recordings, many=True).data)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        uploaded = request.FILES.get("audio")
        if uploaded is None:
            return Response({"audio": "没有收到录音文件。"}, status=400)
        project = _project_for_input(workspace, request.data.get("project_id"))
        if request.data.get("project_id") and project is None:
            return Response({"project_id": "工程不存在。"}, status=400)
        try:
            duration_ms = max(0, int(request.data.get("duration_ms") or 0))
        except (TypeError, ValueError):
            return Response({"duration_ms": "录音时长必须是整数。"}, status=400)
        recording = Recording.objects.create(
            organization=request.organization,
            workspace=workspace,
            project=project,
            name=Path(request.data.get("name") or uploaded.name).name[:255],
            audio=uploaded,
            mime_type=uploaded.content_type or "audio/webm",
            duration_ms=duration_ms,
            created_by=request.user,
        )
        return Response(RecordingSerializer(recording).data, status=status.HTTP_201_CREATED)


class RecordingDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def delete(self, request, organization_id, application_id, recording_id):
        workspace = _workspace(organization_id, application_id)
        recording = workspace and workspace.recordings.filter(id=recording_id).first()
        if recording is None:
            return _not_found("录音")
        recording.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RecordingTranscribeView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def post(self, request, organization_id, application_id, recording_id):
        workspace = _workspace(organization_id, application_id)
        recording = workspace and workspace.recordings.filter(id=recording_id).first()
        if recording is None:
            return _not_found("录音")
        try:
            text = transcribe_audio(recording.audio.path, workspace.transcription_language)
        except Exception as exc:
            return Response(
                {"detail": f"语音转写失败：{exc}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        recording.transcription = text
        recording.save(update_fields=["transcription", "updated_at"])
        return Response(RecordingSerializer(recording).data)


class CopywritingListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        items = workspace.copywritings.all()
        project_id = request.query_params.get("project")
        if project_id:
            items = items.filter(project_id=project_id)
        return Response(CopywritingSerializer(items, many=True).data)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        project = _project_for_input(workspace, request.data.get("project_id"))
        if request.data.get("project_id") and project is None:
            return Response({"project_id": "工程不存在。"}, status=400)
        serializer = CopywritingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            organization=request.organization,
            workspace=workspace,
            project=project,
            created_by=request.user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CopywritingGenerateView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        input_serializer = GenerateCopywritingSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        project = _project_for_input(workspace, data.get("project_id"))
        if data.get("project_id") and project is None:
            return Response({"project_id": "工程不存在。"}, status=400)
        item = Copywriting.objects.create(
            organization=request.organization,
            workspace=workspace,
            project=project,
            title=data["topic"],
            content=generate_copywriting(data["topic"], data["style"]),
            style=data["style"],
            created_by=request.user,
        )
        return Response(CopywritingSerializer(item).data, status=status.HTTP_201_CREATED)


class CopywritingDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def _item(self, workspace, copywriting_id):
        return workspace and workspace.copywritings.filter(id=copywriting_id).first()

    def patch(self, request, organization_id, application_id, copywriting_id):
        workspace = _workspace(organization_id, application_id)
        item = self._item(workspace, copywriting_id)
        if item is None:
            return _not_found("文案")
        serializer = CopywritingSerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, organization_id, application_id, copywriting_id):
        workspace = _workspace(organization_id, application_id)
        item = self._item(workspace, copywriting_id)
        if item is None:
            return _not_found("文案")
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScriptListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        scripts = workspace.scripts.prefetch_related("scenes__image_asset")
        project_id = request.query_params.get("project")
        if project_id:
            scripts = scripts.filter(project_id=project_id)
        return Response(ScriptSerializer(scripts, many=True).data)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        project = _project_for_input(workspace, request.data.get("project_id"))
        if request.data.get("project_id") and project is None:
            return Response({"project_id": "工程不存在。"}, status=400)
        serializer = ScriptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            organization=request.organization,
            workspace=workspace,
            project=project,
            created_by=request.user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ScriptDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def _script(self, workspace, script_id):
        return workspace and workspace.scripts.prefetch_related("scenes__image_asset").filter(id=script_id).first()

    def patch(self, request, organization_id, application_id, script_id):
        workspace = _workspace(organization_id, application_id)
        script = self._script(workspace, script_id)
        if script is None:
            return _not_found("脚本")
        serializer = ScriptSerializer(script, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, organization_id, application_id, script_id):
        workspace = _workspace(organization_id, application_id)
        script = self._script(workspace, script_id)
        if script is None:
            return _not_found("脚本")
        script.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SceneListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def post(self, request, organization_id, application_id, script_id):
        workspace = _workspace(organization_id, application_id)
        script = workspace and workspace.scripts.filter(id=script_id).first()
        if script is None:
            return _not_found("脚本")
        serializer = SceneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image_asset = None
        image_asset_id = request.data.get("image_asset_id")
        if image_asset_id:
            image_asset = MediaAsset.objects.filter(
                id=image_asset_id,
                project__workspace=workspace,
                kind=MediaAsset.Kind.IMAGE,
            ).first()
            if image_asset is None:
                return Response({"image_asset_id": "图片素材不存在。"}, status=400)
        max_order = script.scenes.aggregate(value=Max("order"))["value"]
        next_order = 0 if max_order is None else max_order + 1
        scene = serializer.save(script=script, image_asset=image_asset, order=next_order)
        return Response(SceneSerializer(scene).data, status=status.HTTP_201_CREATED)


class SceneDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def _scene(self, workspace, script_id, scene_id):
        return Scene.objects.select_related("script__workspace", "image_asset").filter(
            id=scene_id,
            script_id=script_id,
            script__workspace=workspace,
        ).first()

    def patch(self, request, organization_id, application_id, script_id, scene_id):
        workspace = _workspace(organization_id, application_id)
        scene = self._scene(workspace, script_id, scene_id)
        if scene is None:
            return _not_found("场景")
        data = request.data.copy()
        data.pop("order", None)
        serializer = SceneSerializer(scene, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, organization_id, application_id, script_id, scene_id):
        workspace = _workspace(organization_id, application_id)
        scene = self._scene(workspace, script_id, scene_id)
        if scene is None:
            return _not_found("场景")
        script = scene.script
        with transaction.atomic():
            scene.delete()
            for order, item in enumerate(script.scenes.order_by("order", "created_at")):
                if item.order != order:
                    Scene.objects.filter(pk=item.pk).update(order=order)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScriptExportView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id, script_id):
        workspace = _workspace(organization_id, application_id)
        script = workspace and workspace.scripts.prefetch_related("scenes").filter(id=script_id).first()
        if script is None:
            return _not_found("脚本")
        lines = [f"=== {script.title} ===", ""]
        if script.description:
            lines.extend([script.description, ""])
        for index, scene in enumerate(script.scenes.all(), start=1):
            lines.extend([
                f"场景 {index}: {scene.title}",
                f"时长: {scene.duration_seconds} 秒",
                f"描述: {scene.description}",
                "",
            ])
        return Response({"filename": f"{script.title}.txt", "content": "\n".join(lines)})
