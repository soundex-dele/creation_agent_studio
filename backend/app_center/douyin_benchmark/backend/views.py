from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import ValidationError
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from modules.tenancy.permissions import HasPathOrganizationRole
from .access import application_for, account_for
from .models import Account, Task, Snapshot, ScriptVersion
from .serializers import AccountInput, AccountSerializer, TaskInput, TaskSerializer, ScriptEdit, VersionSerializer
from .serializers import AccountPage, TaskPage, ConnectionSerializer, WorkResultSerializer, UploadInput, AccountCreated
from .services import start, cancel, Conflict
from .provider import CollectionError, work_web_url, ordered_media_urls
from .collector_config import LocalDTKClient, config_for, public_config, private_config, cipher, invoke
from .models import CollectorConfig
from .serializers import CollectorConfigInput, CollectorConfigOutput
from django.views.decorators.debug import sensitive_variables
from .scoring import rank
from .media import store_upload, path_for
from .analysis import markdown


IDEMPOTENCY = openapi.Parameter("Idempotency-Key", openapi.IN_HEADER, type=openapi.TYPE_STRING, required=True, description="同键同参重放；同键异参返回409。")

def page(request, queryset, serializer):
    paginator = Paginator(queryset, 20)
    current = paginator.get_page(request.query_params.get("page", 1))
    return {"count": paginator.count, "results": serializer(current.object_list, many=True).data}


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]

    def app(self):
        return application_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"])

    def account(self, lock=False):
        return account_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"], self.kwargs["account_id"], lock=lock)

    def task(self, lock=False):
        account = self.account(lock)
        qs = account.tasks.select_related("run")
        return get_object_or_404(qs.select_for_update() if lock else qs, pk=self.kwargs["task_id"])


class AnimationIntegrationsView(BaseView):
    def get(self, request, **kwargs):
        from apps.applications.models import Application
        from core.resource_access import accessible_resources
        app = self.app()
        targets = accessible_resources(Application.objects.for_organization(app.organization_id).filter(
            slug="animation-studio", kind="custom", is_active=True), request.user, operation="run")
        return Response([{"id": target.id, "name": target.name} for target in targets])


class ConnectionView(BaseView):
    @swagger_auto_schema(responses={200: ConnectionSerializer})
    def get(self, request, **kwargs):
        app = self.app()
        try:
            LocalDTKClient(application=app, owner=request.user).validate()
            return Response({"connected": True, "message": "采集配置与运行环境已就绪；Cookie 有效性和平台可用性以实际采集为准。"})
        except CollectionError as exc:
            return Response({"connected": False, "code": exc.code, "message": str(exc)})


class CollectorConfigView(BaseView):
    @swagger_auto_schema(responses={200: CollectorConfigOutput})
    def get(self, request, **kwargs):
        return Response(public_config(config_for(self.app(), request.user)))

    @swagger_auto_schema(request_body=CollectorConfigInput, responses={200: CollectorConfigOutput})
    @sensitive_variables()
    def put(self, request, **kwargs):
        app = self.app()
        serializer = CollectorConfigInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        cookies = values.pop("cookies", "").strip()
        existing = config_for(app, request.user)
        try:
            if not cookies:
                cookies = private_config(existing)["cookies"]
            invoke("validate", {**values, "cookies": cookies})
        except CollectionError as exc:
            raise ValidationError({"detail": str(exc), "code": exc.code}) from None
        config, _ = CollectorConfig.objects.update_or_create(organization_id=app.organization_id,
            application=app, owner=request.user, defaults={**values, "encrypted_cookies": cipher().encrypt(cookies.encode()).decode()})
        return Response(public_config(config))

    @swagger_auto_schema(responses={204: "已清除个人采集配置"})
    def delete(self, request, **kwargs):
        CollectorConfig.objects.filter(organization_id=self.kwargs["organization_id"], application=self.app(), owner=request.user).delete()
        return Response(status=204)


class AccountsView(BaseView):
    @swagger_auto_schema(responses={200: AccountPage})
    def get(self, request, **kwargs):
        qs = Account.objects.filter(application=self.app(), owner=request.user)
        search = request.query_params.get("search", "")[:200]
        if search:
            qs = qs.filter(name__icontains=search)
        return Response(page(request, qs, AccountSerializer))

    @swagger_auto_schema(request_body=AccountInput, manual_parameters=[IDEMPOTENCY], responses={201: AccountCreated})
    @transaction.atomic
    def post(self, request, **kwargs):
        app = self.app()
        serializer = AccountInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        account, created = Account.objects.get_or_create(application=app, owner=request.user, organization_id=app.organization_id,
            source_url=values["source"], defaults={"group": values["group"], "notes": values["notes"]})
        account = self.account_by_id(account.pk)
        task = start(account, {"kind": "collect", "count": values["count"]}, request.headers.get("Idempotency-Key"))
        return Response({**AccountSerializer(account).data, "task": TaskSerializer(task).data, "reused": not created}, status=201 if created else 200)

    def account_by_id(self, pk):
        return account_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"], pk, lock=True)


class AccountView(BaseView):
    @swagger_auto_schema(responses={200: AccountSerializer})
    def get(self, request, **kwargs):
        return Response(AccountSerializer(self.account()).data)

    @swagger_auto_schema(request_body=AccountSerializer, responses={200: AccountSerializer})
    @transaction.atomic
    def patch(self, request, **kwargs):
        serializer = AccountSerializer(self.account(True), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, **kwargs):
        account = self.account(True)
        for task in account.tasks.select_related("run"):
            cancel(task)
        # Private files are cleaned by the maintenance command after rows are removed.
        account.delete()
        return Response(status=204)


class WorksView(BaseView):
    @swagger_auto_schema(responses={200: WorkResultSerializer})
    def get(self, request, **kwargs):
        account = self.account()
        batch_id = request.query_params.get("batch_id")
        batches = account.tasks.filter(kind="collect", snapshots__isnull=False).distinct()
        batch = get_object_or_404(batches, pk=batch_id) if batch_id else batches.first()
        if not batch:
            return Response({"items": [], "sample_size": 0, "median_likes": None, "explanation": "请先采集作品。", "batch": None})
        snapshots = list(Snapshot.objects.filter(batch=batch).select_related("work"))
        result = rank([{**s.data, "url": work_web_url(s.data), "id": str(s.work_id), "has_upload": bool(s.work.media_key),
            "video_url": next(iter(ordered_media_urls(s.work.media_urls)), "")} for s in snapshots], snapshots[0].captured_at)
        search = request.query_params.get("search", "").lower()[:200]
        result["items"] = [i for i in result["items"] if search in i["title"].lower() and
            (request.query_params.get("outstanding") != "true" or i["outstanding"])]
        sort = request.query_params.get("sort", "likes")
        if sort not in ("likes", "comments", "collects", "shares", "published_at", "ratio"):
            raise ValidationError("排序字段无效。")
        result["items"].sort(key=lambda i: (i.get(sort) is not None, i.get(sort) or ("" if sort == "published_at" else 0)), reverse=True)
        result["batch"] = TaskSerializer(batch).data
        response = Response(result)
        response["Cache-Control"] = "private, no-store"
        return response


class UploadView(BaseView):
    parser_classes = [MultiPartParser, FormParser]

    @swagger_auto_schema(request_body=UploadInput)
    def post(self, request, **kwargs):
        account = self.account()
        work = get_object_or_404(account.works, pk=kwargs["work_id"])
        upload = request.FILES.get("video")
        if not upload:
            raise ValidationError("请选择原视频文件。")
        try:
            key = store_upload(upload)
        except ValueError as exc:
            raise ValidationError(str(exc))
        with transaction.atomic():
            account = self.account(True)
            work = get_object_or_404(account.works.select_for_update(), pk=work.pk)
            work.media_key = key
            work.save(update_fields=["media_key", "updated_at"])
        return Response({"id": str(work.pk), "has_upload": True})


class TasksView(BaseView):
    @swagger_auto_schema(responses={200: TaskPage})
    def get(self, request, **kwargs):
        qs = self.account().tasks.select_related("run")
        if request.query_params.get("kind"):
            qs = qs.filter(kind=request.query_params["kind"])
        return Response(page(request, qs, TaskSerializer))

    @swagger_auto_schema(request_body=TaskInput, manual_parameters=[IDEMPOTENCY], responses={201: TaskSerializer})
    @transaction.atomic
    def post(self, request, **kwargs):
        account = self.account(True)
        serializer = TaskInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = start(account, serializer.validated_data, request.headers.get("Idempotency-Key"))
        return Response(TaskSerializer(task).data, status=201)


class TaskView(BaseView):
    @swagger_auto_schema(responses={200: TaskSerializer})
    def get(self, request, **kwargs):
        return Response(TaskSerializer(self.task()).data)


class CancelView(BaseView):
    @transaction.atomic
    def post(self, request, **kwargs):
        task = self.task(True)
        cancel(task)
        return Response(TaskSerializer(task).data)


class FrameView(BaseView):
    def get(self, request, **kwargs):
        task = self.task()
        frame = next((f for f in task.output.get("frames", []) if f["id"] == kwargs["frame_id"]), None)
        if not frame:
            from django.http import Http404
            raise Http404()
        path = path_for(frame["key"])
        if not path.is_file():
            from django.http import Http404
            raise Http404()
        response = FileResponse(path.open("rb"), content_type="image/jpeg")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class VersionsView(BaseView):
    @swagger_auto_schema(responses={200: VersionSerializer(many=True)})
    def get(self, request, **kwargs):
        return Response(VersionSerializer(self.task().versions.all(), many=True).data)

    @swagger_auto_schema(request_body=ScriptEdit, responses={201: VersionSerializer})
    @transaction.atomic
    def post(self, request, **kwargs):
        task = self.task(True)
        if task.kind not in ("script", "rewrite") or not task.run or task.run.status != "succeeded":
            raise ValidationError("请选择已完成的脚本或改写文案。")
        serializer = ScriptEdit(data=request.data, context={"kind": task.kind})
        serializer.is_valid(raise_exception=True)
        latest = task.versions.first()
        if not latest or latest.revision != serializer.validated_data["revision"]:
            raise Conflict("脚本已被更新，请重新加载后保存。")
        version = ScriptVersion.objects.create(task=task, revision=latest.revision + 1, content=serializer.validated_data["content"])
        return Response(VersionSerializer(version).data, status=201)


class DownloadView(BaseView):
    def get(self, request, **kwargs):
        task = self.task()
        version = get_object_or_404(task.versions, pk=kwargs["version_id"])
        body = version.content["text"] if task.kind == "rewrite" else markdown(version.content)
        response = HttpResponse(body, content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="douyin-{task.kind}-v{version.revision}.md"'
        return response


class BrandsView(BaseView):
    def get(self, request, **kwargs):
        app = self.app()
        from app_center.brand_library.backend.views import private_profiles
        profiles = private_profiles(app.organization_id, request.user)
        return Response([{"id": str(p.pk), "name": p.name} for p in profiles[:100]])
