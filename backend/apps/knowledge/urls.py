from django.urls import path

from .views import (
    KnowledgeAnswerRunView,
    KnowledgeBaseDetailView,
    KnowledgeBaseListView,
    KnowledgeDocumentContentView,
    KnowledgeDocumentDetailView,
    KnowledgeDocumentListView,
    KnowledgeDocumentReindexView,
    KnowledgeSearchView,
)


urlpatterns = [
    path("knowledge-bases/", KnowledgeBaseListView.as_view(), name="knowledge-base-list"),
    path("knowledge-bases/<int:pk>/", KnowledgeBaseDetailView.as_view(), name="knowledge-base-detail"),
    path("knowledge-bases/<int:pk>/documents/", KnowledgeDocumentListView.as_view(), name="knowledge-document-list"),
    path("knowledge-bases/<int:pk>/documents/<int:document_id>/", KnowledgeDocumentDetailView.as_view(), name="knowledge-document-detail"),
    path("knowledge-bases/<int:pk>/documents/<int:document_id>/reindex/", KnowledgeDocumentReindexView.as_view(), name="knowledge-document-reindex"),
    path("knowledge-bases/<int:pk>/documents/<int:document_id>/content/", KnowledgeDocumentContentView.as_view(), name="knowledge-document-content"),
    path("knowledge-search/", KnowledgeSearchView.as_view(), name="knowledge-search"),
    path("knowledge-answer-runs/", KnowledgeAnswerRunView.as_view(), name="knowledge-answer-run"),
]
