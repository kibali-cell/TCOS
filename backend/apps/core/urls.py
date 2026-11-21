from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("csrf/", views.CsrfView.as_view(), name="csrf"),
]
