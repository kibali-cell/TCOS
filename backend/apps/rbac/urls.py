from django.urls import path

from . import views

urlpatterns = [
    path("catalogue/", views.CatalogueView.as_view(), name="rbac-catalogue"),
    path("roles/", views.RoleListView.as_view(), name="rbac-roles"),
    path("roles/<uuid:pk>/", views.RoleDetailView.as_view(), name="rbac-role"),
    path("roles/<uuid:pk>/grants/", views.RoleGrantsView.as_view(), name="rbac-role-grants"),
    path("users/<uuid:user_id>/roles/", views.UserRoleListView.as_view(), name="rbac-user-roles"),
    path(
        "users/<uuid:user_id>/roles/<uuid:pk>/",
        views.UserRoleDetailView.as_view(),
        name="rbac-user-role",
    ),
    path("departments/", views.DepartmentListView.as_view(), name="rbac-departments"),
]
