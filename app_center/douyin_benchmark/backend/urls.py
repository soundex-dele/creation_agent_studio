from django.urls import path
from . import views
from .cases import WorkCaseView

root = "applications/<int:application_id>/douyin-benchmark"
account = root + "/accounts/<uuid:account_id>"
task = account + "/tasks/<uuid:task_id>"
urlpatterns = [
    path(root + '/works/<uuid:work_id>/case', WorkCaseView.as_view()),
    path(root + "/animation-integrations", views.AnimationIntegrationsView.as_view()),
    path(root + "/collector-config", views.CollectorConfigView.as_view()),
    path(root + "/connection", views.ConnectionView.as_view()),
    path(root + "/brands", views.BrandsView.as_view()),
    path(root + "/accounts", views.AccountsView.as_view()),
    path(account, views.AccountView.as_view()),
    path(account + "/works", views.WorksView.as_view()),
    path(account + "/works/<uuid:work_id>/upload", views.UploadView.as_view()),
    path(account + "/tasks", views.TasksView.as_view()),
    path(task, views.TaskView.as_view()),
    path(task + "/download", views.AccountAnalysisDownloadView.as_view()),
    path(task + "/cancel", views.CancelView.as_view()),
    path(task + "/frames/<str:frame_id>", views.FrameView.as_view()),
    path(task + "/versions", views.VersionsView.as_view()),
    path(task + "/versions/<uuid:version_id>/download", views.DownloadView.as_view()),
]


from . import research_views as rv
from .owned import VoiceVersionsView
from . import knowledge_views as kv
urlpatterns += [
    path(root + '/knowledge-cards', kv.KnowledgeCardsView.as_view()),
    path(root + '/knowledge-cards/confirm', kv.KnowledgeConfirmView.as_view()),
    path(root + '/knowledge-cards/recommend', kv.KnowledgeRecommendView.as_view()),
    path(root + '/knowledge-cards/<uuid:card_id>', kv.KnowledgeCardsView.as_view()),
    path(root + '/knowledge-cards/<uuid:card_id>/retry-index', kv.KnowledgeRetryView.as_view()),
    path(root + '/knowledge-cards/<uuid:card_id>/shares', kv.KnowledgeSharesView.as_view()),
]
for resource in rv.RESOURCES:
    urlpatterns += [
        path(root + '/' + resource, rv.RecordsView.as_view(), {'resource': resource}),
        path(root + '/' + resource + '/<uuid:record_id>', rv.RecordsView.as_view(), {'resource': resource}),
    ]
urlpatterns += [
    path(root + '/creator-profiles/<uuid:profile_id>/voice-versions', VoiceVersionsView.as_view()),
    path(root + '/creator-profiles/<uuid:profile_id>/voice-versions/<uuid:version_id>/activate', VoiceVersionsView.as_view()),
    path(root + '/works', rv.AllWorksView.as_view()),
    path(root + '/works/<uuid:work_id>/trend', rv.TrendView.as_view()),
    path(root + '/works/<uuid:work_id>/comments', rv.CommentsView.as_view()),
    path(root + '/comparisons', rv.ComparisonView.as_view()),
    path(root + '/publications/summary', rv.PublicationSummaryView.as_view()),
    path(root + '/tasks', rv.ResearchTasksView.as_view()),
    path(root + '/tasks/<uuid:task_id>', rv.ResearchTaskView.as_view()),
    path(root + '/tasks/<uuid:task_id>/cancel', rv.ResearchCancelView.as_view()),
    path(root + '/tasks/<uuid:task_id>/frames/<str:frame_id>', rv.ResearchFrameView.as_view()),
    path(root + '/tasks/<uuid:task_id>/versions', rv.ResearchVersionsView.as_view()),
    path(root + '/tasks/<uuid:task_id>/versions/<uuid:version_id>/download', rv.ResearchDownloadView.as_view()),
    path(root + '/tasks/<uuid:task_id>/apply', rv.VariantApplyView.as_view()),
    path(root + '/subscriptions/<uuid:record_id>/refresh', rv.SubscriptionRefreshView.as_view()),
]
