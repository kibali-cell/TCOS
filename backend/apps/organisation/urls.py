from django.urls import path

from . import views

urlpatterns = [
    path("tree/", views.TreeView.as_view(), name="org-tree"),
    path("options/", views.OptionsView.as_view(), name="org-options"),
    path("people/", views.PeopleView.as_view(), name="org-people"),
    path("departments/", views.DepartmentListView.as_view(), name="org-departments"),
    path("departments/<uuid:pk>/", views.DepartmentDetailView.as_view(), name="org-department"),
    path("departments/<uuid:pk>/head/", views.DepartmentHeadView.as_view(), name="org-head"),
    path(
        "departments/<uuid:pk>/archive/",
        views.DepartmentArchiveView.as_view(),
        name="org-department-archive",
    ),
    path(
        "departments/<uuid:pk>/restore/",
        views.DepartmentRestoreView.as_view(),
        name="org-department-restore",
    ),
    path(
        "departments/<uuid:pk>/approval-chains/",
        views.DepartmentChainsView.as_view(),
        name="org-chains",
    ),
    path(
        "departments/<uuid:pk>/approval-chains/<str:request_type>/",
        views.DepartmentChainDetailView.as_view(),
        name="org-chain",
    ),
    path("positions/", views.PositionListView.as_view(), name="org-positions"),
    path("positions/<uuid:pk>/", views.PositionDetailView.as_view(), name="org-position"),
    path(
        "positions/<uuid:pk>/archive/",
        views.PositionArchiveView.as_view(),
        name="org-position-archive",
    ),
    path(
        "positions/<uuid:pk>/restore/",
        views.PositionRestoreView.as_view(),
        name="org-position-restore",
    ),
    path("assignments/", views.AssignmentListView.as_view(), name="org-assignments"),
    path("assignments/<uuid:pk>/", views.AssignmentDetailView.as_view(), name="org-assignment"),
    path(
        "assignments/<uuid:pk>/end/", views.AssignmentEndView.as_view(), name="org-assignment-end"
    ),
    path(
        "assignments/<uuid:pk>/transfer/",
        views.AssignmentTransferView.as_view(),
        name="org-assignment-transfer",
    ),
    path(
        "assignments/<uuid:pk>/make-primary/",
        views.AssignmentMakePrimaryView.as_view(),
        name="org-assignment-primary",
    ),
]
