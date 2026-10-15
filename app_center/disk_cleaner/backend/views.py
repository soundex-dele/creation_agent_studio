from datetime import timedelta
from contextlib import contextmanager
import platform

from django.core import signing
from django.db import connection, transaction, OperationalError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import filesystem as fs
from .access import application_for
from .models import CleanerEntry, CleanerHost, CleanerPreview, CleanerResult, CleanerTask
from .serializers import CleanupInput, EntrySerializer, PreviewInput, ScanInput, TaskSerializer

SALT = "disk-cleaner-preview-v1"


class DatabaseBusy(APIException):
    status_code = 503
    default_detail = "数据库暂时繁忙，请使用相同请求重试。"


@contextmanager
def queue_transaction():
    # The SQLite connection is thread-local. Acquire its writer reservation
    # before checking a confirmation, rather than upgrading a deferred read.
    immediate = connection.vendor == "sqlite" and not connection.in_atomic_block
    previous = getattr(connection, "transaction_mode", None)
    if immediate:
        connection.transaction_mode = "IMMEDIATE"
    try:
        with transaction.atomic():
            yield
    finally:
        if immediate:
            connection.transaction_mode = previous


def validated(serializer, data):
    result = serializer(data=data)
    result.is_valid(raise_exception=True)
    return result.validated_data


def page(request, queryset, serialize):
    pager = PageNumberPagination()
    pager.page_size = 50
    rows = pager.paginate_queryset(queryset, request)
    return {"count": pager.page.paginator.count, "results": serialize(rows)}


class BaseView(APIView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.app = application_for(request, kwargs["organization_id"], kwargs["application_id"])
        self.host = fs.host_id()

    def tasks(self):
        return CleanerTask.objects.for_organization(self.app.organization_id).filter(
            application=self.app, owner=self.request.user, host=self.host)

    def supported(self):
        if not fs.supported():
            raise ValidationError("首版仅支持 Windows 后端主机。")

    def handle_exception(self, exc):
        if isinstance(exc, (fs.UnsafePath, OSError)):
            exc = ValidationError(str(exc))
        elif isinstance(exc, OperationalError):
            exc = DatabaseBusy()
        return super().handle_exception(exc)


class HostView(BaseView):
    def get(self, request, **kwargs):
        host = CleanerHost.objects.filter(pk=self.host).first()
        online = bool(host and host.heartbeat_at and host.heartbeat_at > timezone.now() - timedelta(seconds=30))
        return Response({"id": self.host, "name": platform.node(), "supported": fs.supported(),
                         "worker_online": online, "volumes": fs.volumes(), "cache_roots": fs.cache_roots()})


class DirectoryView(BaseView):
    def get(self, request, **kwargs):
        self.supported()
        root = fs.validate_root(request.query_params.get("path", ""), "analysis")
        # Bounded listing, no recursive traversal in an HTTP request.
        import os
        items = []
        truncated = False
        with os.scandir(root) as children:
            for i, child in enumerate(children):
                if i >= 10000:
                    truncated = True
                    break
                try:
                    path = fs.Path(child.path)
                    if child.is_dir(follow_symlinks=False) and not fs.protected(path):
                        fs.no_reparse(path)
                        items.append({"path": str(path), "name": child.name})
                except (OSError, fs.UnsafePath):
                    continue
        items.sort(key=lambda x: x["name"].casefold())
        return Response({"path": str(root), "parent": str(root.parent), "directories": items, "truncated": truncated})


class TaskList(BaseView):
    def get(self, request, **kwargs):
        return Response(page(request, self.tasks().order_by("-created_at"), lambda rows: TaskSerializer(rows, many=True).data))

    def post(self, request, **kwargs):
        self.supported()
        values = validated(ScanInput, request.data)
        key = values.pop("request_key")
        existing = self.tasks().filter(request_key=key).first()
        if existing:
            if existing.kind != "scan" or existing.parameters["input"] != values:
                raise ValidationError("请求键已用于其他参数，请生成新的请求键。")
            return Response(TaskSerializer(existing).data)
        root = fs.validate_root(values["root"], values["mode"])
        parameters = {"input": values, "root": str(root), "mode": values["mode"],
                      "minimum_bytes": values["minimum_bytes"], "root_identity": fs.snapshot(root)}
        task, created = CleanerTask.objects.get_or_create(
            organization=self.app.organization, application=self.app, owner=request.user, host=self.host, request_key=key,
            defaults={"kind": "scan", "parameters": parameters})
        if task.kind != "scan" or task.parameters["input"] != values:
            raise ValidationError("请求键已用于其他参数。")
        return Response(TaskSerializer(task).data, status=201 if created else 200)


class TaskDetail(BaseView):
    def get(self, request, pk, **kwargs):
        return Response(TaskSerializer(get_object_or_404(self.tasks(), pk=pk)).data)

    def post(self, request, pk, **kwargs):
        task = get_object_or_404(self.tasks(), pk=pk)
        self.tasks().filter(pk=task.pk, state__in=["queued", "running"]).update(cancel_requested=True)
        task.refresh_from_db()
        return Response(TaskSerializer(task).data)


class EntryList(BaseView):
    def get(self, request, pk, **kwargs):
        task = get_object_or_404(self.tasks(), pk=pk)
        order = request.query_params.get("sort", "-size")
        if order not in {"size", "-size", "path", "-modified_at"}:
            raise ValidationError("排序无效。")
        if task.kind == "cleanup":
            rows = task.results.select_related("entry").order_by("id")
            return Response(page(request, rows, lambda items: [
                {**EntrySerializer(item.entry).data, "state": item.state, "reason": item.reason} for item in items]))
        entries = task.entries.all()
        if task.parameters["mode"] == "analysis":
            entries = entries.filter(parent=request.query_params.get("parent", task.parameters["root"]))
        return Response(page(request, entries.order_by(order, "id"), lambda rows: EntrySerializer(rows, many=True).data))


class PreviewList(BaseView):
    def post(self, request, **kwargs):
        self.supported()
        values = validated(PreviewInput, request.data)
        scan = get_object_or_404(self.tasks(), pk=values["scan_id"], kind="scan", state="completed")
        if scan.parameters["mode"] == "analysis":
            raise ValidationError("空间分析不能直接删除文件，请选择目录进行大文件扫描。")
        ids = sorted({str(pk) for pk in values["entry_ids"]})
        entries = list(scan.entries.filter(pk__in=ids, cleanable=True))
        if len(entries) != len(ids):
            raise ValidationError("选中项不属于本次扫描或不允许清理。")
        preview = CleanerPreview.objects.create(scan=scan, owner=request.user, entry_ids=ids,
            total_bytes=sum(item.size for item in entries), expires_at=timezone.now() + timedelta(minutes=10))
        return Response({"id": str(preview.id), "token": signing.dumps(str(preview.id), salt=SALT),
                         "count": len(ids), "total_bytes": preview.total_bytes, "expires_at": preview.expires_at,
                         "host_name": platform.node(), "root": scan.parameters["root"]}, status=201)


class PreviewDetail(BaseView):
    def get(self, request, pk, **kwargs):
        preview = get_object_or_404(CleanerPreview, pk=pk, scan__in=self.tasks(), owner=request.user)
        return Response(page(request, CleanerEntry.objects.filter(task=preview.scan, pk__in=preview.entry_ids).order_by("path"),
                             lambda rows: EntrySerializer(rows, many=True).data))


class CleanupList(BaseView):
    def post(self, request, **kwargs):
        self.supported()
        values = validated(CleanupInput, request.data)
        try:
            preview_id = signing.loads(values["token"], salt=SALT)
        except signing.BadSignature:
            raise ValidationError("清理预览凭据无效，请重新预览。") from None
        with queue_transaction():
            preview = get_object_or_404(CleanerPreview.objects.select_for_update(), pk=preview_id,
                                       scan__in=self.tasks(), owner=request.user)
            old = self.tasks().filter(request_key=values["request_key"]).first()
            if old:
                if old.preview_id != preview.pk:
                    raise ValidationError("请求键已用于其他清理，请重新预览。")
                return Response(TaskSerializer(old).data)
            old = self.tasks().filter(preview=preview).first()
            if old:
                return Response(TaskSerializer(old).data)
            if preview.expires_at <= timezone.now():
                raise ValidationError("清理预览已过期，请重新预览。")
            task = CleanerTask.objects.create(organization=self.app.organization, application=self.app, owner=request.user,
                host=self.host, kind="cleanup", request_key=values["request_key"], preview=preview, source=preview.scan,
                parameters=preview.scan.parameters)
            CleanerResult.objects.bulk_create([CleanerResult(task=task, entry_id=pk) for pk in preview.entry_ids])
        return Response(TaskSerializer(task).data, status=201)
