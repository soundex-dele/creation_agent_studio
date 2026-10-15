"""Application-owned policies registered with the trusted host."""
from modules.platform_api.extensions import ApplicationContributions


def validate_reference(data):
    from .backend.serializers import BrandReferenceSerializer
    serializer = BrandReferenceSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def reference_fields():
    from .backend.serializers import BrandReferenceSerializer
    return BrandReferenceSerializer().get_fields()


def resolve_snapshot(**kwargs):
    from .backend.context import resolve_brand_snapshot
    return resolve_brand_snapshot(**kwargs)


def compose_snapshot(**kwargs):
    from .backend.context import compose_with_brand_snapshot
    return compose_with_brand_snapshot(**kwargs)


provider = ApplicationContributions(validate_brand_reference=validate_reference, brand_reference_fields=reference_fields,
                                   resolve_brand_snapshot=resolve_snapshot, compose_brand_snapshot=compose_snapshot)
