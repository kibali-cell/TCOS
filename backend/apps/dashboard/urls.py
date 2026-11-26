from django.urls import path

from . import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path(
        "departments/<uuid:pk>/",
        views.DepartmentDashboardView.as_view(),
        name="department-dashboard",
    ),
]
