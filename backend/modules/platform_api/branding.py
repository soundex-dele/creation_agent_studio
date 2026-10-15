"""Brand reference wire contract; application providers own validation and resolution."""
from rest_framework import serializers
from apps.applications.app_center.extensions import call_unique_contribution


class BrandReferenceSerializer(serializers.Serializer):
    def get_fields(self):
        # Preserve field metadata for schema generation and serializer introspection.
        return call_unique_contribution('brand_reference_fields')

    def to_internal_value(self, data):
        return call_unique_contribution('validate_brand_reference', data)


def resolve_brand_snapshot(**kwargs):
    return call_unique_contribution('resolve_brand_snapshot', **kwargs)


def compose_with_brand_snapshot(**kwargs):
    return call_unique_contribution('compose_brand_snapshot', **kwargs)
