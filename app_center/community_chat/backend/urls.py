from django.urls import path
from . import media, views

urlpatterns = [
    path('users/', views.UsersView.as_view()),
    path('rooms/', views.RoomsView.as_view()),
    path('rooms/<uuid:room_id>/', views.RoomView.as_view()),
    path('rooms/<uuid:room_id>/messages/', views.MessagesView.as_view()),
    path('rooms/<uuid:room_id>/messages/<int:message_id>/withdraw/', views.WithdrawView.as_view()),
    path('rooms/<uuid:room_id>/read/', views.ReadView.as_view()),
    path('rooms/<uuid:room_id>/uploads/', media.UploadView.as_view()),
    path('attachments/<uuid:attachment_id>/access/', media.AccessView.as_view()),
    path('content/', media.ContentView.as_view()),
    path('ticket/', views.TicketView.as_view()),
]
