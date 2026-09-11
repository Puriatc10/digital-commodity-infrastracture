from django.urls import path
from documents.api.views import DocumentUploadView, DocumentDownloadView, DocumentListView

urlpatterns = [
    path("api/documents/", DocumentListView.as_view(), name="document-list"),
    path("api/documents/upload/", DocumentUploadView.as_view(), name="document-upload"),
    path("api/documents/<uuid:pk>/download/", DocumentDownloadView.as_view(), name="document-download"),
]
