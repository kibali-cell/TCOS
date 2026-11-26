from django.urls import path

from . import views

urlpatterns = [
    path("events/", views.EventListView.as_view(), name="audit-events"),
    path("events/<int:pk>/", views.EventDetailView.as_view(), name="audit-event"),
    path("event-types/", views.EventTypesView.as_view(), name="audit-event-types"),
    path("export/", views.ExportView.as_view(), name="audit-export"),
]
