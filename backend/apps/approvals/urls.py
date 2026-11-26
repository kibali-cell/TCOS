from django.urls import path

from . import views

urlpatterns = [
    path("requests/", views.RequestListView.as_view(), name="approval-requests"),
    path("requests/<uuid:pk>/", views.RequestDetailView.as_view(), name="approval-request"),
    path("requests/<uuid:pk>/submit/", views.SubmitView.as_view(), name="approval-submit"),
    path("requests/<uuid:pk>/cancel/", views.CancelView.as_view(), name="approval-cancel"),
    path("requests/<uuid:pk>/comment/", views.CommentView.as_view(), name="approval-comment"),
    path("requests/<uuid:pk>/review/", views.ReviewView.as_view(), name="approval-review"),
    path("requests/<uuid:pk>/approve/", views.ApproveView.as_view(), name="approval-approve"),
    path("requests/<uuid:pk>/reject/", views.RejectView.as_view(), name="approval-reject"),
    path("summary/", views.SummaryView.as_view(), name="approval-summary"),
    path("notifications/", views.NotificationListView.as_view(), name="approval-notifications"),
    path("role-grants/", views.RoleGrantRequestView.as_view(), name="approval-role-grants"),
    path("tzs-limits/", views.TzsLimitsView.as_view(), name="approval-tzs"),
    path("tzs-limits/propose/", views.TzsProposeView.as_view(), name="approval-tzs-propose"),
]
