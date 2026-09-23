import json

from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination

from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from modules.tenancy.permissions import HasPathOrganizationRole

from .serializers import IdeaSerializer, ListFilters, TodoSerializer


class EntryPagination(PageNumberPagination):
    page_size = 20


class PersonalEntryMixin:
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER
    pagination_class = EntryPagination

    def get_application(self):
        if not hasattr(self, "_application"):
            self._application = get_object_or_404(
                accessible_resources(
                    Application.objects.for_organization(self.kwargs["organization_id"]).filter(
                        is_active=True, slug="ideas-todos", kind=Application.Kind.CUSTOM,
                    ), self.request.user, operation="run",
                ), pk=self.kwargs["application_id"],
            )
        return self._application

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        return self.serializer_class.Meta.model.objects.for_organization(
            self.kwargs["organization_id"],
        ).filter(application=self.get_application(), owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(
            application=self.get_application(),
            organization_id=self.kwargs["organization_id"], owner=self.request.user,
        )


class IdeaListView(PersonalEntryMixin, generics.ListCreateAPIView):
    serializer_class = IdeaSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        filters = ListFilters(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        search = filters.validated_data.get("search")
        tag = filters.validated_data.get("tag")
        if search:
            queryset = queryset.filter(Q(title__icontains=search) | Q(body__icontains=search))
        if tag:
            # SQLite stores non-ASCII JSON as escapes; PostgreSQL uses Unicode.
            queryset = queryset.filter(
                Q(tags__icontains=json.dumps(tag, ensure_ascii=False)[1:-1])
                | Q(tags__icontains=json.dumps(tag, ensure_ascii=True)[1:-1]),
            )
        return queryset


class IdeaDetailView(PersonalEntryMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = IdeaSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]


class TodoListView(PersonalEntryMixin, generics.ListCreateAPIView):
    serializer_class = TodoSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        filters = ListFilters(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        values = filters.validated_data
        state = values["status"]
        if state != "all":
            queryset = queryset.filter(is_completed=state == "completed")
        if state == "today":
            queryset = queryset.filter(due_date=values["today"])
        elif state == "overdue":
            queryset = queryset.filter(due_date__lt=values["today"])
        if values.get("search"):
            queryset = queryset.filter(
                Q(title__icontains=values["search"]) | Q(description__icontains=values["search"]),
            )
        if "priority" in values:
            queryset = queryset.filter(priority=values["priority"])
        return queryset.order_by(
            "is_completed", F("due_date").asc(nulls_last=True), "-priority", "-created_at", "id",
        )


class TodoDetailView(PersonalEntryMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TodoSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]
