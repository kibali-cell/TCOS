from django.urls import path

from . import user_views as views

urlpatterns = [
    path("", views.UserListView.as_view(), name="users"),
    path("<uuid:pk>/", views.UserDetailView.as_view(), name="user"),
    path("<uuid:pk>/status/", views.UserStatusView.as_view(), name="user-status"),
    path("<uuid:pk>/unlock/", views.UserUnlockView.as_view(), name="user-unlock"),
    path(
        "<uuid:pk>/temporary-password/",
        views.UserTemporaryPasswordView.as_view(),
        name="user-temporary-password",
    ),
]
