"""Root URL configuration. All API routes live under /api/v1/."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/rbac/", include("apps.rbac.urls")),
    path("api/v1/organisation/", include("apps.organisation.urls")),
    path("api/v1/audit/", include("apps.audit.urls")),
    path("api/v1/", include("apps.core.urls")),
]
