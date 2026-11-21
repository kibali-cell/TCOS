from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="auth-me"),
    path("sessions/", views.SessionListView.as_view(), name="auth-sessions"),
    path("sessions/end-others/", views.EndOtherSessionsView.as_view(), name="auth-end-others"),
    path("sessions/<uuid:pk>/", views.SessionDetailView.as_view(), name="auth-session-detail"),
    path("password/change/", views.PasswordChangeView.as_view(), name="auth-password-change"),
]
