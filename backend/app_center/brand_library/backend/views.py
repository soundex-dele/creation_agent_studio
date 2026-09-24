from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from modules.tenancy.permissions import HasPathOrganizationRole
from .models import BrandProfile
from .serializers import ProfileSerializer, ProductSerializer, ExampleSerializer


def available_applications(organization_id, user):
    return accessible_resources(Application.objects.for_organization(organization_id).filter(
        slug="brand-library", kind=Application.Kind.CUSTOM, is_active=True,
    ), user, operation="run")


def private_profiles(organization_id, user):
    return BrandProfile.objects.for_organization(organization_id).filter(
        owner=user, application__in=available_applications(organization_id, user),
    )


class BrandPagination(PageNumberPagination):
    page_size = 20


class BrandMixin:
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER
    pagination_class = BrandPagination

    def get_application(self):
        return get_object_or_404(available_applications(self.kwargs["organization_id"], self.request.user), pk=self.kwargs["application_id"])

    def get_profile(self):
        return get_object_or_404(private_profiles(self.kwargs["organization_id"], self.request.user),
                               application=self.get_application(), pk=self.kwargs["profile_id"])

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        if "profile_id" in self.kwargs:
            profile = self.get_profile()
            queryset = self.serializer_class.Meta.model.objects.for_organization(profile.organization_id).filter(
                application=profile.application, owner=self.request.user, profile=profile,
            )
        else:
            queryset = private_profiles(self.kwargs["organization_id"], self.request.user)
            if "application_id" in self.kwargs:
                queryset = queryset.filter(application=self.get_application())
        search = self.request.query_params.get("search", "").strip()
        if len(search) > 200:
            raise ValidationError({"search": "搜索内容不能超过 200 字。"})
        return queryset.filter(name__icontains=search) if search else queryset

    @transaction.atomic
    def perform_create(self, serializer):
        extra = {"profile": self.get_profile()} if "profile_id" in self.kwargs else {}
        serializer.save(application=self.get_application(), owner=self.request.user,
                        organization_id=self.kwargs["organization_id"], **extra)
        self.touch_profile()

    @transaction.atomic
    def perform_update(self, serializer):
        serializer.save()
        self.touch_profile()

    @transaction.atomic
    def perform_destroy(self, instance):
        instance.delete()
        self.touch_profile()

    def touch_profile(self):
        if "profile_id" in self.kwargs:
            BrandProfile.objects.filter(pk=self.kwargs["profile_id"]).update(updated_at=timezone.now())


class ProfileList(BrandMixin, generics.ListCreateAPIView):
    serializer_class = ProfileSerializer


class ProfileChoices(BrandMixin, generics.ListAPIView):
    serializer_class = ProfileSerializer


class ProfileDetail(BrandMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProfileSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]


class ProductList(BrandMixin, generics.ListCreateAPIView):
    serializer_class = ProductSerializer


class ProductDetail(ProfileDetail):
    serializer_class = ProductSerializer


class ExampleList(BrandMixin, generics.ListCreateAPIView):
    serializer_class = ExampleSerializer


class ExampleDetail(ProfileDetail):
    serializer_class = ExampleSerializer
