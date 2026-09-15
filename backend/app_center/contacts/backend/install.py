"""Idempotent organization installation hook for Contacts."""


def install(*, organization, application):
    from .models import AddressBook

    AddressBook.objects.update_or_create(
        application=application,
        defaults={"organization": organization, "name": "企业通讯录"},
    )
