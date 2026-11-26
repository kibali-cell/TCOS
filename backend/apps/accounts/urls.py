from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("login/2fa/", views.LoginTwoFactorView.as_view(), name="auth-login-2fa"),
    path("password/forgot/", views.ForgotPasswordView.as_view(), name="auth-password-forgot"),
    path("password/reset/", views.ResetPasswordView.as_view(), name="auth-password-reset"),
    path("2fa/", views.TwoFactorStatusView.as_view(), name="auth-2fa"),
    path("2fa/enrol/", views.TwoFactorEnrolView.as_view(), name="auth-2fa-enrol"),
    path("2fa/confirm/", views.TwoFactorConfirmView.as_view(), name="auth-2fa-confirm"),
    path("2fa/disable/", views.TwoFactorDisableView.as_view(), name="auth-2fa-disable"),
    path(
        "2fa/recovery-codes/",
        views.TwoFactorRecoveryCodesView.as_view(),
        name="auth-2fa-recovery-codes",
    ),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="auth-me"),
    path("sessions/", views.SessionListView.as_view(), name="auth-sessions"),
    path("sessions/end-others/", views.EndOtherSessionsView.as_view(), name="auth-end-others"),
    path("sessions/<uuid:pk>/", views.SessionDetailView.as_view(), name="auth-session-detail"),
    path("password/change/", views.PasswordChangeView.as_view(), name="auth-password-change"),
]
