from django.urls import path

from . import views


urlpatterns = [
    path("applications/<int:application_id>/creation-toolbox/workspace", views.WorkspaceView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/projects", views.ProjectListView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/projects/<uuid:project_id>", views.ProjectDetailView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/projects/<uuid:project_id>/folders", views.FolderListView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/projects/<uuid:project_id>/folders/<uuid:folder_id>", views.FolderDetailView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/projects/<uuid:project_id>/assets", views.AssetListView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/projects/<uuid:project_id>/assets/<uuid:asset_id>", views.AssetDetailView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/recordings", views.RecordingListView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/recordings/<uuid:recording_id>", views.RecordingDetailView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/recordings/<uuid:recording_id>/transcribe", views.RecordingTranscribeView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/copywritings", views.CopywritingListView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/copywritings/generate", views.CopywritingGenerateView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/copywritings/<uuid:copywriting_id>", views.CopywritingDetailView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/scripts", views.ScriptListView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/scripts/<uuid:script_id>", views.ScriptDetailView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/scripts/<uuid:script_id>/scenes", views.SceneListView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/scripts/<uuid:script_id>/scenes/<uuid:scene_id>", views.SceneDetailView.as_view()),
    path("applications/<int:application_id>/creation-toolbox/scripts/<uuid:script_id>/export", views.ScriptExportView.as_view()),
]

