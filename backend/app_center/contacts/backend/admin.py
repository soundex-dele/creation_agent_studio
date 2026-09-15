from django.contrib import admin

from .models import AddressBook, Contact, ContactMethod


class ContactMethodInline(admin.TabularInline):
    model = ContactMethod
    extra = 0


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "department", "organization", "updated_at")
    list_filter = ("organization", "company", "department")
    search_fields = ("name", "company", "department", "methods__value")
    inlines = (ContactMethodInline,)


admin.site.register(AddressBook)
