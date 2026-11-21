"""Fails if any API view is added without an explicit permission policy."""

from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.views import APIView

from apps.rbac.permissions import RBACPermission

# Views that are deliberately open or only need a signed-in user. Anything else must use
# RBACPermission with an `rbac_module`. Adding to this list is a security decision.
EXPLICITLY_OPEN = {
    "apps.core.views.HealthView",
    "apps.core.views.CsrfView",
    "apps.accounts.views.LoginView",
}
SIGNED_IN_ONLY = {  # IsSignedIn: the user's own account, no module permission applies
    "apps.accounts.views.LogoutView",
    "apps.accounts.views.MeView",
    "apps.accounts.views.SessionListView",
    "apps.accounts.views.EndOtherSessionsView",
    "apps.accounts.views.SessionDetailView",
    "apps.accounts.views.PasswordChangeView",
}


def all_view_classes():
    found = {}

    def walk(patterns, prefix=""):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                callback = entry.callback
                view_class = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
                found[prefix + str(entry.pattern)] = (view_class, callback)

    walk(get_resolver("config.urls").url_patterns)  # production routes, not test-only ones
    return found


def declares_permissions(view_class) -> bool:
    """True if the class or a project base class sets permission_classes itself."""
    return any(
        "permission_classes" in vars(klass)
        for klass in view_class.__mro__
        if klass is not APIView and not klass.__module__.startswith("rest_framework")
    )


def dotted(view_class) -> str:
    return f"{view_class.__module__}.{view_class.__qualname__}"


def test_the_url_scan_finds_the_views():
    views = all_view_classes()
    assert len(views) >= 15
    assert any("rbac/roles" in path for path in views)


def test_every_route_is_a_drf_view():
    """A plain Django view would bypass the permission engine entirely."""
    for path, (view_class, _callback) in all_view_classes().items():
        assert view_class is not None and issubclass(view_class, APIView), path


def test_every_view_declares_its_permission_policy():
    missing = [
        path
        for path, (view_class, _cb) in all_view_classes().items()
        if not declares_permissions(view_class)
    ]
    assert missing == [], f"Views without an explicit permission_classes: {missing}"


def test_rbac_views_name_their_module_and_other_views_are_on_the_allow_lists():
    problems = []
    for path, (view_class, _cb) in all_view_classes().items():
        name = dotted(view_class)
        uses_rbac = RBACPermission in view_class.permission_classes
        if uses_rbac:
            if not getattr(view_class, "rbac_module", None):
                problems.append(f"{path}: RBACPermission without rbac_module")
        elif name not in EXPLICITLY_OPEN | SIGNED_IN_ONLY:
            problems.append(f"{path}: {name} is not RBACPermission and not on an allow list")
    assert problems == []


def test_open_views_really_are_the_only_unauthenticated_ones(new_client):
    for url in ("/api/v1/rbac/roles/", "/api/v1/rbac/catalogue/", "/api/v1/auth/me/"):
        assert new_client().get(url).status_code == 401, url


def test_default_permission_class_is_the_central_engine():
    from django.conf import settings

    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "apps.rbac.permissions.RBACPermission"
    ]


def test_the_guard_itself_would_catch_a_forgotten_policy():
    class Forgotten(APIView):
        pass

    class Configured(APIView):
        permission_classes = [RBACPermission]

    assert not declares_permissions(Forgotten)
    assert declares_permissions(Configured)
