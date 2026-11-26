from django.urls import path

from . import document_views, views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("csrf/", views.CsrfView.as_view(), name="csrf"),
    path("documents/", document_views.DocumentListView.as_view(), name="documents"),
    path(
        "documents/<uuid:pk>/download/",
        document_views.DocumentDownloadView.as_view(),
        name="document-download",
    ),
    path(
        "documents/<uuid:pk>/archive/",
        document_views.DocumentArchiveView.as_view(),
        name="document-archive",
    ),
]
