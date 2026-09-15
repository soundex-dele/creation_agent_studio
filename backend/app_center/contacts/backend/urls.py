from django.urls import path

from .views import AddressBookView, ContactDetailView, ContactListView


app_name = "contacts"

urlpatterns = [
    path(
        "applications/<int:application_id>/address-book",
        AddressBookView.as_view(),
        name="address-book",
    ),
    path(
        "applications/<int:application_id>/contacts",
        ContactListView.as_view(),
        name="contact-list",
    ),
    path(
        "applications/<int:application_id>/contacts/<uuid:contact_id>",
        ContactDetailView.as_view(),
        name="contact-detail",
    ),
]
