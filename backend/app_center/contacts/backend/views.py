from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.enterprise.models import Membership
from modules.tenancy.permissions import HasPathOrganizationRole

from .models import AddressBook, Contact
from .serializers import AddressBookSerializer, ContactSerializer


class ContactPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _address_book(organization_id, application_id):
    return AddressBook.objects.for_organization(organization_id).filter(
        application_id=application_id,
        application__organization_id=organization_id,
        application__is_active=True,
    ).first()


def _contact(organization_id, application_id, contact_id, *, for_update=False):
    contacts = Contact.objects.for_organization(organization_id)
    if for_update:
        contacts = contacts.select_for_update()
    return contacts.select_related(
        "address_book"
    ).prefetch_related("methods").filter(
        id=contact_id,
        address_book__application_id=application_id,
        deleted_at__isnull=True,
    ).first()


class AddressBookView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        book = _address_book(organization_id, application_id)
        if book is None:
            return Response({"detail": "通讯录不存在。"}, status=status.HTTP_404_NOT_FOUND)
        book.contact_count = book.contacts.filter(deleted_at__isnull=True).count()
        return Response(AddressBookSerializer(book).data)


class ContactListView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id):
        book = _address_book(organization_id, application_id)
        if book is None:
            return Response({"detail": "通讯录不存在。"}, status=status.HTTP_404_NOT_FOUND)
        contacts = book.contacts.filter(deleted_at__isnull=True).prefetch_related("methods")
        query = request.query_params.get("q", "").strip()
        if query:
            contacts = contacts.filter(
                Q(name__icontains=query)
                | Q(company__icontains=query)
                | Q(department__icontains=query)
                | Q(job_title__icontains=query)
                | Q(methods__value__icontains=query)
            ).distinct()
        for field in ("company", "department"):
            value = request.query_params.get(field, "").strip()
            if value:
                contacts = contacts.filter(**{field: value})
        ordering = request.query_params.get("ordering", "name")
        if ordering not in {"name", "-name", "updated_at", "-updated_at", "created_at", "-created_at"}:
            ordering = "name"
        contacts = contacts.order_by(ordering, "id")
        paginator = ContactPagination()
        page = paginator.paginate_queryset(contacts, request, view=self)
        return paginator.get_paginated_response(ContactSerializer(page, many=True).data)

    def post(self, request, organization_id, application_id):
        book = _address_book(organization_id, application_id)
        if book is None:
            return Response({"detail": "通讯录不存在。"}, status=status.HTTP_404_NOT_FOUND)
        serializer = ContactSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            organization=request.organization,
            address_book=book,
            created_by=request.user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ContactDetailView(APIView):
    permission_classes = (HasPathOrganizationRole,)

    def get(self, request, organization_id, application_id, contact_id):
        contact = _contact(organization_id, application_id, contact_id)
        if contact is None:
            return Response({"detail": "联系人不存在。"}, status=status.HTTP_404_NOT_FOUND)
        return Response(ContactSerializer(contact).data)

    def patch(self, request, organization_id, application_id, contact_id):
        with transaction.atomic():
            contact = _contact(
                organization_id, application_id, contact_id, for_update=True
            )
            if contact is None:
                return Response({"detail": "联系人不存在。"}, status=status.HTTP_404_NOT_FOUND)
            expected_version = request.data.get("version")
            if expected_version is None:
                return Response({"version": "更新联系人时必须提供当前版本。"}, status=400)
            try:
                expected_version = int(expected_version)
            except (TypeError, ValueError):
                return Response({"version": "版本必须是整数。"}, status=400)
            if expected_version != contact.version:
                return Response(
                    {"detail": "联系人已被其他用户更新，请刷新后重试。", "current_version": contact.version},
                    status=status.HTTP_409_CONFLICT,
                )
            data = request.data.copy()
            data.pop("version", None)
            serializer = ContactSerializer(contact, data=data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

    def delete(self, request, organization_id, application_id, contact_id):
        role = request.organization_membership.role
        if not request.user.is_superuser and role not in (
            Membership.Role.OWNER, Membership.Role.ADMIN
        ):
            return Response({"detail": "只有组织管理员可以删除联系人。"}, status=403)
        with transaction.atomic():
            contact = _contact(
                organization_id, application_id, contact_id, for_update=True
            )
            if contact is None:
                return Response({"detail": "联系人不存在。"}, status=status.HTTP_404_NOT_FOUND)
            contact.deleted_at = timezone.now()
            contact.version += 1
            contact.save(update_fields=["deleted_at", "version", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
