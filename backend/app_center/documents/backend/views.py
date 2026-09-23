from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.conversations.models import Conversation
from apps.conversations.serializers import ConversationDetailSerializer
from apps.conversations.execution import create_conversation_run, ConversationRunActive
from apps.enterprise.models import Membership
from modules.tenancy.permissions import HasPathOrganizationRole
from modules.execution.api.serializers import RunSerializer
from modules.execution.application.errors import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition
from .access import application_for, document_for, visible_documents
from .content import plain_text
from .models import Document, DocumentGrant, DocumentSession
from .serializers import DocumentSerializer, DocumentUpdateSerializer, GrantSerializer, AssistantSerializer


class VersionConflict(APIException):
    status_code = 409
    default_detail = "文档已被修改，请保留草稿后重新加载。"


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        return application_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"])

    def document(self, **options):
        return document_for(self.request.user, self.kwargs["organization_id"], self.kwargs["application_id"], self.kwargs["pk"], **options)

    def serialize(self, doc):
        return DocumentSerializer(doc, context={"request": self.request}).data


class DocumentList(BaseView):
    def get(self, request, **kwargs):
        queryset = visible_documents(request.user, kwargs["organization_id"], kwargs["application_id"])
        scope = request.query_params.get("scope", "mine")
        if scope not in {"mine", "shared"}:
            raise ValidationError({"scope": "请选择我的文档或共享给我。"})
        queryset = queryset.filter(owner=request.user) if scope == "mine" else queryset.exclude(owner=request.user)
        search = request.query_params.get("search", "").strip()[:200]
        if search:
            queryset = queryset.filter(Q(title__icontains=search) | Q(plain_text__icontains=search))
        pagination = PageNumberPagination()
        pagination.page_size = 20
        items = pagination.paginate_queryset(queryset, request)
        data = [self.serialize(item) for item in items]
        for item in data:
            item.pop("content")
            item["plain_text"] = item["plain_text"][:160]
        return pagination.get_paginated_response(data)

    def post(self, request, **kwargs):
        application = self.application()
        serializer = DocumentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        doc = serializer.save(organization=application.organization, application=application, owner=request.user)
        doc.plain_text = plain_text(doc.content)
        doc.save(update_fields=["plain_text"])
        return Response(self.serialize(doc), status=201)


class DocumentDetail(BaseView):
    def get(self, request, **kwargs):
        return Response(self.serialize(self.document()))

    @transaction.atomic
    def patch(self, request, **kwargs):
        doc = self.document(edit=True, lock=True)
        serializer = DocumentUpdateSerializer(doc, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if "version" not in serializer.validated_data:
            raise ValidationError({"version": "保存必须提供版本号。"})
        if serializer.validated_data["version"] != doc.version:
            raise VersionConflict()
        content = serializer.validated_data.get("content", doc.content)
        doc = serializer.save(version=doc.version + 1, plain_text=plain_text(content))
        return Response(self.serialize(doc))

    @transaction.atomic
    def delete(self, request, **kwargs):
        doc = self.document(owner=True, lock=True)
        # Keep Run audit history, but remove private conversation resources.
        conversation_ids = list(doc.sessions.values_list("conversation_id", flat=True))
        doc.delete()
        Conversation.objects.filter(pk__in=conversation_ids).delete()
        return Response(status=204)


class DocumentCopy(BaseView):
    def post(self, request, **kwargs):
        source = self.document()
        serializer = DocumentSerializer(data={
            "title": request.data.get("title", source.title[:197] + " 副本"),
            "content": request.data.get("content", source.content),
        }, context={"request": request})
        serializer.is_valid(raise_exception=True)
        doc = serializer.save(organization=source.organization, application=source.application,
                              owner=request.user, plain_text=plain_text(serializer.validated_data["content"]))
        return Response(self.serialize(doc), status=201)


class DocumentDownload(BaseView):
    def get(self, request, **kwargs):
        doc = self.document()
        response = HttpResponse(doc.plain_text, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = content_disposition_header(True, f"{doc.title}.txt")
        return response


class DocumentMembers(BaseView):
    def get(self, request, **kwargs):
        self.application()
        search = request.query_params.get("search", "").strip()[:100]
        members = Membership.objects.filter(organization_id=kwargs["organization_id"], is_active=True, user__is_active=True).exclude(user=request.user)
        if search:
            members = members.filter(user__username__icontains=search)
        return Response(list(members.order_by("user__username").values("user_id", "user__username")[:50]))


class DocumentShares(BaseView):
    def get(self, request, **kwargs):
        doc = self.document(owner=True)
        return Response(list(doc.grants.order_by("user__username").values("user_id", "user__username", "role")))

    @transaction.atomic
    def post(self, request, **kwargs):
        doc = self.document(owner=True, lock=True)
        serializer = GrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_id = serializer.validated_data["user_id"]
        if user_id == doc.owner_id or not Membership.objects.filter(
            organization_id=doc.organization_id, user_id=user_id, user__is_active=True, is_active=True,
        ).exists():
            raise ValidationError({"user_id": "请选择其他有效组织成员。"})
        DocumentGrant.objects.update_or_create(document=doc, user_id=user_id, defaults={"role": serializer.validated_data["role"]})
        return Response(serializer.validated_data)

    @transaction.atomic
    def delete(self, request, **kwargs):
        doc = self.document(owner=True, lock=True)
        try:
            user_id = int(request.query_params.get("user_id", ""))
        except ValueError:
            raise ValidationError({"user_id": "请选择成员。"})
        doc.grants.filter(user_id=user_id).delete()
        return Response(status=204)


class DocumentConversation(BaseView):
    @transaction.atomic
    def post(self, request, **kwargs):
        doc = self.document(lock=True)
        session = doc.sessions.filter(user=request.user).first()
        if session is None:
            conversation = Conversation.objects.create(organization=doc.organization, user=request.user, title=f"在线文档：{doc.title}"[:200])
            session = DocumentSession.objects.create(document=doc, user=request.user, conversation=conversation)
        return Response({"id": str(session.conversation_id)})

    def get(self, request, **kwargs):
        doc = self.document()
        from django.shortcuts import get_object_or_404
        session = get_object_or_404(DocumentSession, document=doc, user=request.user)
        data = ConversationDetailSerializer(session.conversation, context={"request": request}).data
        contexts = {str(m.run_id): (m.metadata or {}).get("document_context") for m in session.conversation.messages.filter(role="user") if (m.metadata or {}).get("document_context")}
        for source, value in zip(session.conversation.messages.all(), data["messages"]):
            if source.role == "assistant" and contexts.get(str(source.run_id)):
                value["metadata"] = {**(value.get("metadata") or {}), "document_context": contexts[str(source.run_id)]}
        return Response(data)


class DocumentAssistant(BaseView):
    def post(self, request, **kwargs):
        doc = self.document()
        serializer = AssistantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        if doc.version != values["version"]:
            raise VersionConflict()
        key = (request.headers.get("Idempotency-Key") or "").strip()
        if not key or len(key) > 160:
            raise ValidationError({"detail": "必须提供有效的 Idempotency-Key。"})
        from django.shortcuts import get_object_or_404
        session = get_object_or_404(DocumentSession, document=doc, user=request.user)
        context = {key: values[key] for key in ("version", "selection", "selection_from", "selection_to")}
        try:
            with transaction.atomic():
                self.document(lock=True)
                run, _ = create_conversation_run(request.user, session.conversation, values["content"], key, document_context=context)
        except (DeploymentUnavailable, InvalidExecutionDefinition, IdempotencyKeyReused, ConversationRunActive) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(RunSerializer(run).data, status=202)


from modules.execution.api.views import OrganizationRunCommandsView


class DocumentRunCommands(OrganizationRunCommandsView):
    """Readers may cancel/answer their own document runs, regardless of tenant role."""
    minimum_role = Membership.Role.VIEWER

    def post(self, request, organization_id, application_id, pk, run_id):
        from django.shortcuts import get_object_or_404
        from modules.execution.models import Run
        doc = document_for(request.user, organization_id, application_id, pk)
        get_object_or_404(Run, pk=run_id, organization_id=organization_id, owner=request.user, input__document_id=str(doc.pk))
        return super().post(request, organization_id, run_id)
