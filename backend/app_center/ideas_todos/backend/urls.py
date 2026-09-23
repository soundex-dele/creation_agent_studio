from django.urls import path

from . import views


urlpatterns = [
    path("applications/<int:application_id>/ideas-todos/ideas", views.IdeaListView.as_view()),
    path("applications/<int:application_id>/ideas-todos/ideas/<uuid:pk>", views.IdeaDetailView.as_view()),
    path("applications/<int:application_id>/ideas-todos/todos", views.TodoListView.as_view()),
    path("applications/<int:application_id>/ideas-todos/todos/<uuid:pk>", views.TodoDetailView.as_view()),
]
