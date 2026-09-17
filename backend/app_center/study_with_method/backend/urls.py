from django.urls import path

from . import views


app_name = "study_with_method"

urlpatterns = [
    path("applications/<int:application_id>/study/dashboard", views.DashboardView.as_view(), name="dashboard"),
    path("applications/<int:application_id>/study/profile", views.ProfileView.as_view(), name="profile"),
    path("applications/<int:application_id>/study/tasks", views.TaskListView.as_view(), name="tasks"),
    path("applications/<int:application_id>/study/tasks/<uuid:task_id>", views.TaskDetailView.as_view(), name="task-detail"),
    path("applications/<int:application_id>/study/problems", views.ProblemListView.as_view(), name="problems"),
    path("applications/<int:application_id>/study/problems/<uuid:problem_id>", views.ProblemDetailView.as_view(), name="problem-detail"),
    path("applications/<int:application_id>/study/problems/<uuid:problem_id>/hint", views.ProblemHintView.as_view(), name="problem-hint"),
    path("applications/<int:application_id>/study/problems/<uuid:problem_id>/variant", views.ProblemVariantView.as_view(), name="problem-variant"),
    path("applications/<int:application_id>/study/problems/<uuid:problem_id>/attempts", views.AttemptCreateView.as_view(), name="attempt-create"),
    path("applications/<int:application_id>/study/mistakes", views.MistakeListView.as_view(), name="mistakes"),
    path("applications/<int:application_id>/study/mistakes/<uuid:mistake_id>", views.MistakeDetailView.as_view(), name="mistake-detail"),
    path("applications/<int:application_id>/study/reviews", views.ReviewListView.as_view(), name="reviews"),
    path("applications/<int:application_id>/study/reviews/<uuid:review_id>/complete", views.ReviewCompleteView.as_view(), name="review-complete"),
    path("applications/<int:application_id>/study/reports", views.ReportListView.as_view(), name="reports"),
    path("applications/<int:application_id>/study/quizzes", views.QuizListView.as_view(), name="quizzes"),
    path("applications/<int:application_id>/study/quizzes/<uuid:quiz_id>/submit", views.QuizSubmitView.as_view(), name="quiz-submit"),
    path("applications/<int:application_id>/study/guardians", views.GuardianListView.as_view(), name="guardians"),
    path("applications/<int:application_id>/study/guardians/<uuid:link_id>", views.GuardianDetailView.as_view(), name="guardian-detail"),
    path("applications/<int:application_id>/study/export", views.ExportView.as_view(), name="export"),
    path("applications/<int:application_id>/study/data", views.DataDeleteView.as_view(), name="delete-data"),
]
