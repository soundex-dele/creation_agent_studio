from __future__ import annotations

import csv
import io
import mimetypes
import unicodedata
from datetime import date
from pathlib import Path

from django.http import HttpResponse
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.tenancy.permissions import HasPathOrganizationRole
from apps.enterprise.models import Membership

from .models import (
    Copywriting,
    CreationProject,
    CreationWorkspace,
    MaterialFolder,
    MediaAsset,
    MetricSnapshot,
    ProjectStageEvent,
    Publication,
    Recording,
    Scene,
    Script,
    TopicIdea,
    VideoDeliverable,
)
from .serializers import (
    AssetSerializer,
    CopywritingSerializer,
    FolderSerializer,
    MetricSnapshotSerializer,
    ProjectSerializer,
    ProjectStageEventSerializer,
    ProjectStageTransitionSerializer,
    PublicationSerializer,
    RecordingSerializer,
    SceneSerializer,
    ScriptSerializer,
    TopicBulkUpdateSerializer,
    TopicCreateProjectSerializer,
    TopicSerializer,
    VideoDeliverableSerializer,
    WorkspaceSerializer,
)
from .analytics import build_analytics
from .csv_metrics import CSV_FIELDS, commit_metrics_rows, csv_template_text, parse_metrics_csv
from .services import transcribe_audio


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


def _normalize_title(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _is_active_member(workspace, user):
    if user is None:
        return True
    return Membership.objects.filter(
        organization_id=workspace.organization_id,
        user=user,
        is_active=True,
    ).exists()


def _validate_project_relations(workspace, validated_data):
    errors = {}
    topic = validated_data.get("topic")
    if topic is not None and topic.workspace_id != workspace.id:
        errors["topic"] = "选题不属于当前工作区。"
    for field in ("owner", "reviewer"):
        if not _is_active_member(workspace, validated_data.get(field)):
            errors[field] = "请选择当前组织的有效成员。"
    return errors


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
        workspace.topic_count = workspace.topics.count()
        workspace.publication_count = workspace.publications.count()
        return Response(WorkspaceSerializer(workspace).data)

    def patch(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        serializer = WorkspaceSerializer(workspace, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class TopicListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        topics = workspace.topics.select_related("created_by").annotate(
            project_count=Count("projects", distinct=True),
            publication_count=Count("projects__publications", distinct=True),
        )
        search = request.query_params.get("search", "").strip()
        if search:
            topics = topics.filter(
                Q(title__icontains=search)
                | Q(notes__icontains=search)
                | Q(source_name__icontains=search)
                | Q(tags__icontains=search)
            )
        topic_status = request.query_params.get("status", "").strip()
        if topic_status:
            topics = topics.filter(status=topic_status)
        tag = request.query_params.get("tag", "").strip()
        if tag:
            topics = topics.filter(tags__icontains=tag)
        return Response(TopicSerializer(topics, many=True).data)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        serializer = TopicSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        normalized = _normalize_title(serializer.validated_data["title"])
        duplicate = workspace.topics.exclude(status=TopicIdea.Status.ARCHIVED).filter(
            normalized_title=normalized
        ).first()
        if duplicate is not None and not request.data.get("allow_duplicate"):
            return Response({
                "code": "duplicate_topic",
                "detail": "选题库中已有相同标题。",
                "existing": TopicSerializer(duplicate).data,
            }, status=status.HTTP_409_CONFLICT)
        topic = serializer.save(
            organization=request.organization,
            workspace=workspace,
            normalized_title=normalized,
            created_by=request.user,
            updated_by=request.user,
        )
        return Response(TopicSerializer(topic).data, status=status.HTTP_201_CREATED)


class TopicDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    @staticmethod
    def _topic(workspace, topic_id):
        return workspace and workspace.topics.filter(id=topic_id).first()

    def get(self, request, organization_id, application_id, topic_id):
        topic = self._topic(_workspace(organization_id, application_id), topic_id)
        if topic is None:
            return _not_found("选题")
        topic.project_count = topic.projects.count()
        topic.publication_count = Publication.objects.filter(project__topic=topic).count()
        projects = topic.projects.annotate(
            asset_count=Count("assets", distinct=True),
            recording_count=Count("recordings", distinct=True),
            script_count=Count("scripts", distinct=True),
            deliverable_count=Count("deliverables", distinct=True),
            publication_count=Count("publications", distinct=True),
        )
        data = TopicSerializer(topic).data
        data["projects"] = ProjectSerializer(projects, many=True).data
        return Response(data)

    def patch(self, request, organization_id, application_id, topic_id):
        workspace = _workspace(organization_id, application_id)
        topic = self._topic(workspace, topic_id)
        if topic is None:
            return _not_found("选题")
        serializer = TopicSerializer(topic, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        title = serializer.validated_data.get("title", topic.title)
        normalized = _normalize_title(title)
        duplicate = workspace.topics.exclude(id=topic.id).exclude(
            status=TopicIdea.Status.ARCHIVED
        ).filter(normalized_title=normalized).first()
        if duplicate is not None and not request.data.get("allow_duplicate"):
            return Response({
                "code": "duplicate_topic", "detail": "选题库中已有相同标题。",
                "existing": TopicSerializer(duplicate).data,
            }, status=status.HTTP_409_CONFLICT)
        serializer.save(normalized_title=normalized, updated_by=request.user)
        return Response(serializer.data)

    def delete(self, request, organization_id, application_id, topic_id):
        topic = self._topic(_workspace(organization_id, application_id), topic_id)
        if topic is None:
            return _not_found("选题")
        if topic.projects.exists():
            return Response(
                {"detail": "已关联工程的选题不能删除，请改为归档。"},
                status=status.HTTP_409_CONFLICT,
            )
        topic.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TopicBulkUpdateView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        serializer = TopicBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        topics = list(workspace.topics.filter(id__in=serializer.validated_data["ids"]))
        if len(topics) != len(set(serializer.validated_data["ids"])):
            return Response({"ids": "部分选题不存在。"}, status=400)
        add_tags = {item.strip() for item in serializer.validated_data.get("add_tags", []) if item.strip()}
        remove_tags = {item.strip() for item in serializer.validated_data.get("remove_tags", []) if item.strip()}
        with transaction.atomic():
            for topic in topics:
                if "status" in serializer.validated_data:
                    topic.status = serializer.validated_data["status"]
                topic.tags = [item for item in topic.tags if item not in remove_tags]
                topic.tags = list(dict.fromkeys([*topic.tags, *sorted(add_tags)]))[:20]
                topic.updated_by = request.user
                topic.save(update_fields=["status", "tags", "updated_by", "updated_at"])
        return Response(TopicSerializer(topics, many=True).data)


class TopicTagsView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        tags = []
        for values in workspace.topics.order_by("-updated_at").values_list("tags", flat=True):
            for value in values:
                if value not in tags:
                    tags.append(value)
                if len(tags) >= 30:
                    return Response(tags)
        return Response(tags)


class TopicCreateProjectView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def post(self, request, organization_id, application_id, topic_id):
        workspace = _workspace(organization_id, application_id)
        topic = workspace and workspace.topics.filter(id=topic_id).first()
        if topic is None:
            return _not_found("选题")
        serializer = TopicCreateProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        work_type = serializer.validated_data["work_type"]
        work_type_label = CreationProject.WorkType(work_type).label
        suffix = f"-{work_type_label}"
        topic_name = topic.title[: 120 - len(suffix)].rstrip()
        project_name = f"{topic_name}{suffix}"
        if workspace.projects.filter(name=project_name).exists():
            return Response({"name": "同名工程已经存在。"}, status=400)
        with transaction.atomic():
            project = CreationProject.objects.create(
                organization=request.organization,
                workspace=workspace,
                topic=topic,
                name=project_name,
                description=serializer.validated_data.get("description", topic.notes),
                work_type=work_type,
                target_platforms=serializer.validated_data.get(
                    "target_platforms", topic.target_platforms
                ),
                owner=request.user,
                created_by=request.user,
            )
            if topic.status != TopicIdea.Status.ADOPTED:
                topic.status = TopicIdea.Status.ADOPTED
                topic.updated_by = request.user
                topic.save(update_fields=["status", "updated_by", "updated_at"])
        project.asset_count = project.copywriting_count = 0
        project.recording_count = project.script_count = 0
        project.deliverable_count = project.publication_count = 0
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class ProjectListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        projects = workspace.projects.select_related("topic", "owner", "reviewer")
        if request.query_params.get("include_archived") != "true":
            projects = projects.filter(archived_at__isnull=True)
        projects = projects.annotate(
            asset_count=Count("assets", distinct=True),
            copywriting_count=Count("copywritings", distinct=True),
            recording_count=Count("recordings", distinct=True),
            script_count=Count("scripts", distinct=True),
            deliverable_count=Count("deliverables", distinct=True),
            publication_count=Count("publications", distinct=True),
        )
        return Response(ProjectSerializer(projects, many=True).data)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        serializer = ProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        relation_errors = _validate_project_relations(workspace, serializer.validated_data)
        if relation_errors:
            return Response(relation_errors, status=400)
        try:
            serializer.save(
                organization=request.organization,
                workspace=workspace,
                created_by=request.user,
                owner=serializer.validated_data.get("owner") or request.user,
            )
        except IntegrityError:
            return Response({"name": "同名工程已经存在。"}, status=400)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ProjectDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id, project_id):
        workspace = _workspace(organization_id, application_id)
        project = _project(workspace, project_id)
        if project is None:
            return _not_found("工程")
        project.asset_count = project.assets.count()
        project.copywriting_count = project.copywritings.count()
        project.recording_count = project.recordings.count()
        project.script_count = project.scripts.count()
        project.deliverable_count = project.deliverables.count()
        project.publication_count = project.publications.count()
        return Response(ProjectSerializer(project).data)

    def patch(self, request, organization_id, application_id, project_id):
        workspace = _workspace(organization_id, application_id)
        project = _project(workspace, project_id)
        if project is None:
            return _not_found("工程")
        serializer = ProjectSerializer(project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        relation_errors = _validate_project_relations(workspace, serializer.validated_data)
        if relation_errors:
            return Response(relation_errors, status=400)
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


class ProjectArchiveView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def post(self, request, organization_id, application_id, project_id):
        project = _project(_workspace(organization_id, application_id), project_id)
        if project is None:
            return _not_found("工程")
        project.archived_at = None if request.data.get("restore") else timezone.now()
        project.save(update_fields=["archived_at", "updated_at"])
        return Response(ProjectSerializer(project).data)


class ProjectStageTransitionView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id, project_id):
        project = _project(_workspace(organization_id, application_id), project_id)
        if project is None:
            return _not_found("工程")
        return Response(ProjectStageEventSerializer(project.stage_events.all(), many=True).data)

    def post(self, request, organization_id, application_id, project_id):
        workspace = _workspace(organization_id, application_id)
        project = _project(workspace, project_id)
        if project is None:
            return _not_found("工程")
        serializer = ProjectStageTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        next_stage = serializer.validated_data["to_stage"]
        if next_stage == CreationProject.Stage.PUBLISHED and not project.publications.exists():
            return Response({"to_stage": "至少添加一条发布记录后才能标记为已发布。"}, status=400)
        if next_stage == CreationProject.Stage.RETROSPECTIVE and not MetricSnapshot.objects.filter(
            publication__project=project
        ).exists():
            return Response({"to_stage": "至少添加一条指标快照后才能完成复盘。"}, status=400)
        with transaction.atomic():
            previous = project.stage
            project.stage = next_stage
            project.stage_changed_at = timezone.now()
            project.save(update_fields=["stage", "stage_changed_at", "updated_at"])
            event = ProjectStageEvent.objects.create(
                organization=request.organization,
                project=project,
                from_stage=previous,
                to_stage=next_stage,
                note=serializer.validated_data.get("note", ""),
                changed_by=request.user,
            )
        return Response({
            "project": ProjectSerializer(project).data,
            "event": ProjectStageEventSerializer(event).data,
        })


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
        assets = (
            project.assets.all()
            if request.query_params.get("all") == "true"
            else project.assets.filter(folder_id=folder_id)
        )
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


class SceneReorderView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def post(self, request, organization_id, application_id, script_id):
        workspace = _workspace(organization_id, application_id)
        script = workspace and workspace.scripts.prefetch_related("scenes").filter(id=script_id).first()
        if script is None:
            return _not_found("脚本")
        scene_ids = request.data.get("scene_ids")
        if not isinstance(scene_ids, list):
            return Response({"scene_ids": "请提供完整的场景 ID 数组。"}, status=400)
        existing = {str(item.id): item for item in script.scenes.all()}
        if set(scene_ids) != set(existing) or len(scene_ids) != len(existing):
            return Response({"scene_ids": "场景 ID 必须完整且不能重复。"}, status=400)
        with transaction.atomic():
            # Avoid the unique(script, order) constraint while positions are swapped.
            for index, scene_id in enumerate(scene_ids):
                Scene.objects.filter(pk=existing[scene_id].pk).update(order=100000 + index)
            for index, scene_id in enumerate(scene_ids):
                Scene.objects.filter(pk=existing[scene_id].pk).update(order=index)
        script = workspace.scripts.prefetch_related("scenes__image_asset").get(id=script_id)
        return Response(ScriptSerializer(script).data)


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


class DeliverableListView(APIView):
    permission_classes = (HasPathOrganizationRole,)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        items = VideoDeliverable.objects.filter(project__workspace=workspace).select_related(
            "project", "created_by", "reviewed_by"
        )
        project_id = request.query_params.get("project")
        if project_id:
            items = items.filter(project_id=project_id)
        return Response(VideoDeliverableSerializer(items, many=True).data)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        project = _project_for_input(workspace, request.data.get("project"))
        if project is None:
            return Response({"project": "工程不存在。"}, status=400)
        serializer = VideoDeliverableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(
            organization=request.organization, project=project, created_by=request.user
        )
        return Response(VideoDeliverableSerializer(item).data, status=status.HTTP_201_CREATED)


class DeliverableDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    @staticmethod
    def _item(workspace, deliverable_id):
        return workspace and VideoDeliverable.objects.filter(
            project__workspace=workspace, id=deliverable_id
        ).first()

    def patch(self, request, organization_id, application_id, deliverable_id):
        item = self._item(_workspace(organization_id, application_id), deliverable_id)
        if item is None:
            return _not_found("成片")
        serializer = VideoDeliverableSerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        review_status = serializer.validated_data.get("review_status", item.review_status)
        review_values = {}
        if review_status in {
            VideoDeliverable.ReviewStatus.APPROVED,
            VideoDeliverable.ReviewStatus.CHANGES_REQUESTED,
        }:
            review_values = {"reviewed_by": request.user, "reviewed_at": timezone.now()}
        item = serializer.save(**review_values)
        return Response(VideoDeliverableSerializer(item).data)

    def delete(self, request, organization_id, application_id, deliverable_id):
        item = self._item(_workspace(organization_id, application_id), deliverable_id)
        if item is None:
            return _not_found("成片")
        if item.publications.exists():
            return Response({"detail": "已关联发布记录的成片不能删除。"}, status=409)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicationListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        items = workspace.publications.select_related("project", "deliverable").prefetch_related(
            "metric_snapshots"
        )
        if request.query_params.get("project"):
            items = items.filter(project_id=request.query_params["project"])
        if request.query_params.get("platform"):
            items = items.filter(platform=request.query_params["platform"])
        return Response(PublicationSerializer(items, many=True).data)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        project = _project_for_input(workspace, request.data.get("project"))
        if project is None:
            return Response({"project": "工程不存在。"}, status=400)
        deliverable = None
        if request.data.get("deliverable"):
            deliverable = project.deliverables.filter(id=request.data["deliverable"]).first()
            if deliverable is None:
                return Response({"deliverable": "成片不属于当前工程。"}, status=400)
        serializer = PublicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                item = serializer.save(
                    organization=request.organization,
                    workspace=workspace,
                    project=project,
                    deliverable=deliverable,
                    created_by=request.user,
                )
                if project.stage not in {
                    CreationProject.Stage.PUBLISHED, CreationProject.Stage.RETROSPECTIVE
                }:
                    previous = project.stage
                    project.stage = CreationProject.Stage.PUBLISHED
                    project.stage_changed_at = timezone.now()
                    project.save(update_fields=["stage", "stage_changed_at", "updated_at"])
                    ProjectStageEvent.objects.create(
                        organization=request.organization, project=project,
                        from_stage=previous, to_stage=CreationProject.Stage.PUBLISHED,
                        note="添加首条发布记录后自动更新", changed_by=request.user,
                    )
        except IntegrityError:
            return Response({"detail": "该平台作品已经存在。"}, status=409)
        return Response(PublicationSerializer(item).data, status=status.HTTP_201_CREATED)


class PublicationDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    @staticmethod
    def _item(workspace, publication_id):
        return workspace and workspace.publications.filter(id=publication_id).first()

    def patch(self, request, organization_id, application_id, publication_id):
        workspace = _workspace(organization_id, application_id)
        item = self._item(workspace, publication_id)
        if item is None:
            return _not_found("发布记录")
        data = request.data.copy()
        if "project" in data and str(data["project"]) != str(item.project_id):
            return Response({"project": "发布记录不能转移到其他工程。"}, status=400)
        if data.get("deliverable"):
            if not item.project.deliverables.filter(id=data["deliverable"]).exists():
                return Response({"deliverable": "成片不属于当前工程。"}, status=400)
        serializer = PublicationSerializer(item, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except IntegrityError:
            return Response({"detail": "该平台作品已经存在。"}, status=409)
        return Response(serializer.data)

    def delete(self, request, organization_id, application_id, publication_id):
        item = self._item(_workspace(organization_id, application_id), publication_id)
        if item is None:
            return _not_found("发布记录")
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MetricSnapshotListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id, publication_id):
        workspace = _workspace(organization_id, application_id)
        publication = workspace and workspace.publications.filter(id=publication_id).first()
        if publication is None:
            return _not_found("发布记录")
        return Response(MetricSnapshotSerializer(publication.metric_snapshots.all(), many=True).data)

    def post(self, request, organization_id, application_id, publication_id):
        workspace = _workspace(organization_id, application_id)
        publication = workspace and workspace.publications.filter(id=publication_id).first()
        if publication is None:
            return _not_found("发布记录")
        serializer = MetricSnapshotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        snapshot, created = MetricSnapshot.objects.update_or_create(
            publication=publication,
            observed_on=serializer.validated_data["observed_on"],
            defaults={
                **serializer.validated_data,
                "organization": request.organization,
                "created_by": request.user,
            },
        )
        return Response(
            MetricSnapshotSerializer(snapshot).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MetricSnapshotDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def _item(self, workspace, publication_id, snapshot_id):
        return workspace and MetricSnapshot.objects.filter(
            id=snapshot_id,
            publication_id=publication_id,
            publication__workspace=workspace,
        ).first()

    def patch(self, request, organization_id, application_id, publication_id, snapshot_id):
        item = self._item(_workspace(organization_id, application_id), publication_id, snapshot_id)
        if item is None:
            return _not_found("指标快照")
        serializer = MetricSnapshotSerializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, organization_id, application_id, publication_id, snapshot_id):
        item = self._item(_workspace(organization_id, application_id), publication_id, snapshot_id)
        if item is None:
            return _not_found("指标快照")
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AnalyticsView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        try:
            start = date.fromisoformat(request.query_params["start"]) if request.query_params.get("start") else None
            end = date.fromisoformat(request.query_params["end"]) if request.query_params.get("end") else None
        except ValueError:
            return Response({"detail": "日期必须使用 YYYY-MM-DD 格式。"}, status=400)
        return Response(build_analytics(
            workspace, start=start, end=end, platform=request.query_params.get("platform", "")
        ))


class MetricsCsvTemplateView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        if _workspace(organization_id, application_id) is None:
            return _not_found("创作工作区")
        response = HttpResponse("\ufeff" + csv_template_text(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="creation-metrics-template.csv"'
        return response


class MetricsCsvImportView(APIView):
    permission_classes = (HasPathOrganizationRole,)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response({"file": "请选择 CSV 文件。"}, status=400)
        rows, errors = parse_metrics_csv(uploaded, workspace)
        preview = [{
            key: value.isoformat() if hasattr(value, "isoformat") else value
            for key, value in row.items() if key not in {"project"}
        } for row in rows[:50]]
        if errors or str(request.data.get("commit", "")).lower() not in {"1", "true", "yes"}:
            return Response({
                "valid": not errors, "row_count": len(rows), "errors": errors, "preview": preview,
            }, status=status.HTTP_400_BAD_REQUEST if errors else status.HTTP_200_OK)
        result = commit_metrics_rows(
            rows, workspace=workspace, organization=request.organization, user=request.user
        )
        return Response({"valid": True, "errors": [], **result})


class MetricsCsvExportView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        workspace = _workspace(organization_id, application_id)
        if workspace is None:
            return _not_found("创作工作区")
        publications = workspace.publications.select_related("project").prefetch_related(
            "metric_snapshots"
        )
        if request.query_params.get("platform"):
            publications = publications.filter(platform=request.query_params["platform"])
        if request.query_params.get("project"):
            publications = publications.filter(project_id=request.query_params["project"])
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
        writer.writeheader()
        metric_fields = CSV_FIELDS[9:18]
        for publication in publications:
            snapshot = publication.metric_snapshots.order_by("-observed_on", "-created_at").first()
            row = {
                "project_name": publication.project.name,
                "platform": publication.platform,
                "platform_name": publication.platform_name,
                "account_name": publication.account_name,
                "title": publication.title,
                "external_post_id": publication.external_post_id,
                "post_url": publication.post_url,
                "published_at": timezone.localtime(publication.published_at).strftime("%Y-%m-%d %H:%M:%S"),
                "observed_on": snapshot.observed_on.isoformat() if snapshot else "",
                "average_watch_seconds": snapshot.average_watch_seconds if snapshot else "",
            }
            row.update({field: getattr(snapshot, field) if snapshot else "" for field in metric_fields})
            writer.writerow(row)
        response = HttpResponse("\ufeff" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="creation-metrics.csv"'
        return response
