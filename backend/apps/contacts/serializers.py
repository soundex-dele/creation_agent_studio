from django.db import transaction
from rest_framework import serializers

from .models import AddressBook, Contact, ContactMethod


class ContactMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMethod
        fields = ["id", "kind", "label", "value", "is_primary"]
        read_only_fields = ["id"]

    def validate_value(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("联系方式不能为空。")
        return value


class ContactSerializer(serializers.ModelSerializer):
    methods = ContactMethodSerializer(many=True, required=False)

    class Meta:
        model = Contact
        fields = [
            "id", "name", "company", "department", "job_title", "notes",
            "avatar", "version", "methods", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "version", "created_at", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("姓名不能为空。")
        return value

    def validate_methods(self, methods):
        seen = set()
        primary_kinds = set()
        first_by_kind = {}
        for method in methods:
            first_by_kind.setdefault(method["kind"], method)
            identity = (method["kind"], method["value"].casefold())
            if identity in seen:
                raise serializers.ValidationError("存在重复的联系方式。")
            seen.add(identity)
            if method.get("is_primary"):
                if method["kind"] in primary_kinds:
                    raise serializers.ValidationError("每种联系方式只能设置一个主要项。")
                primary_kinds.add(method["kind"])
        for kind, method in first_by_kind.items():
            if kind not in primary_kinds:
                method["is_primary"] = True
        return methods

    @transaction.atomic
    def create(self, validated_data):
        methods = validated_data.pop("methods", [])
        contact = Contact.objects.create(**validated_data)
        ContactMethod.objects.bulk_create(
            ContactMethod(contact=contact, **method) for method in methods
        )
        return contact

    @transaction.atomic
    def update(self, instance, validated_data):
        methods = validated_data.pop("methods", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.version += 1
        instance.save()
        if methods is not None:
            instance.methods.all().delete()
            ContactMethod.objects.bulk_create(
                ContactMethod(contact=instance, **method) for method in methods
            )
            instance._prefetched_objects_cache.pop("methods", None)
        return instance


class AddressBookSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(read_only=True)
    contact_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AddressBook
        fields = ["id", "application_id", "name", "contact_count", "created_at", "updated_at"]
