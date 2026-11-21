"""The single, central permission engine.

Every API view gets its access decisions from here. Nothing else in the code base may
check roles directly (CLAUDE.md section 5).

Concepts
--------
* A permission is a (module, action) pair, e.g. ("finance", "APPROVE").
* A role grants a permission within a scope: ALL, DEPARTMENT, ASSIGNED or OWN.
* ALL covers everything. DEPARTMENT covers records of the user's department and nothing
  else (so a department officer cannot create or reach records in another department).
  ASSIGNED covers records assigned to the user and, because it is wider, records the user
  owns. OWN covers records the user created or is the subject of.
* A user may hold several roles. Effective access is the union over all active role
  assignments (not revoked, inside their valid dates, role active). A role assignment
  limited to one department confines that role's grants to that department.
* Record grants give one user one action on one record regardless of role scope.
* ``is_superuser`` grants nothing here: access comes only from roles and record grants.

Models opt in to scope checks through optional class attributes (defaults shown):
``RBAC_DEPARTMENT_FIELD = "department_id"``, ``RBAC_OWNER_FIELDS = ("created_by_id",)``,
``RBAC_ASSIGNED_FIELDS = ()``.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .constants import ACTIONS, ALL, ASSIGNED, DEPARTMENT, OWN
from .models import RecordGrant, RolePermission, UserRole

DEFAULT_ACTION_BY_METHOD = {
    "GET": "VIEW",
    "HEAD": "VIEW",
    "OPTIONS": "VIEW",
    "POST": "CREATE",
    "PUT": "EDIT",
    "PATCH": "EDIT",
    "DELETE": "DELETE",
}


@dataclass(frozen=True)
class Access:
    """What one user may reach for one (module, action)."""

    everything: bool = False
    departments: frozenset = field(default_factory=frozenset)
    assigned: bool = False
    own: bool = False

    def __bool__(self) -> bool:
        return self.everything or bool(self.departments) or self.assigned or self.own

    def merged(self, other: Access) -> Access:
        return Access(
            everything=self.everything or other.everything,
            departments=self.departments | other.departments,
            assigned=self.assigned or other.assigned,
            own=self.own or other.own,
        )

    @property
    def label(self) -> str:
        """Widest scope, for display."""
        if self.everything:
            return ALL
        if self.departments:
            return DEPARTMENT
        if self.assigned:
            return ASSIGNED
        return OWN


def _contribution(scope: str, department_id, user) -> Access:
    """Access contributed by one grant held through one role assignment."""
    if scope == ALL:
        if department_id is None:
            return Access(everything=True, assigned=True, own=True)
        return Access(departments=frozenset({department_id}))
    if scope == DEPARTMENT:
        home = department_id or user.department_id
        return Access(departments=frozenset({home}) if home else frozenset())
    if scope == ASSIGNED:
        return Access(assigned=True, own=True)
    if scope == OWN:
        return Access(own=True)
    return Access()


def effective_permissions(user) -> dict[tuple[str, str], Access]:
    """All of the user's permissions, combined across every active role."""
    if not (user and getattr(user, "is_authenticated", False) and user.is_active):
        return {}
    today = timezone.localdate()
    assignments = list(
        UserRole.objects.filter(user=user, revoked_at__isnull=True, role__is_active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .values_list("role_id", "department_id")
    )
    if not assignments:
        return {}
    by_role: dict = {}
    for role_id, department_id in assignments:
        by_role.setdefault(role_id, []).append(department_id)

    result: dict[tuple[str, str], Access] = {}
    grants = RolePermission.objects.filter(role_id__in=by_role).values_list(
        "role_id", "permission__module", "permission__action", "scope"
    )
    for role_id, module, action, scope in grants:
        for department_id in by_role[role_id]:
            key = (module, action)
            result[key] = result.get(key, Access()).merged(
                _contribution(scope, department_id, user)
            )
    return result


def _covers(access: Access, user, obj) -> bool:
    if access.everything:
        return True
    model = type(obj)
    department_field = getattr(model, "RBAC_DEPARTMENT_FIELD", "department_id")
    if access.departments and department_field:
        if getattr(obj, department_field, None) in access.departments:
            return True
    if access.own:
        for name in getattr(model, "RBAC_OWNER_FIELDS", ("created_by_id",)):
            if getattr(obj, name, None) == user.pk:
                return True
    if access.assigned:
        for name in getattr(model, "RBAC_ASSIGNED_FIELDS", ()):
            if getattr(obj, name, None) == user.pk:
                return True
    return False


def _live_grants(user, action):
    now = timezone.now()
    return RecordGrant.objects.filter(user=user, action=action, revoked_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )


def can(user, module: str, action: str, obj=None, *, access=None) -> bool:
    """May ``user`` perform ``action`` in ``module`` (on ``obj``, if given)?

    Without ``obj`` the answer is "in at least one scope", which is what a menu or a list
    endpoint needs. With ``obj`` the object must fall inside a scope or be covered by a
    record grant. Pass ``access`` (from :func:`effective_permissions`) to avoid re-querying.
    """
    if action not in ACTIONS or not (user and getattr(user, "is_authenticated", False)):
        return False
    if not user.is_active:
        return False
    if access is None:
        access = effective_permissions(user)
    granted = access.get((module, action))

    if obj is None:
        return bool(granted)
    if granted and _covers(granted, user, obj):
        return True
    if getattr(obj, "pk", None) is None:
        return False
    content_type = ContentType.objects.get_for_model(type(obj))
    return _live_grants(user, action).filter(content_type=content_type, object_id=obj.pk).exists()


def filter_queryset(user, module: str, action: str, queryset, *, access=None):
    """Restrict ``queryset`` to the records ``user`` may reach for ``action``."""
    if action not in ACTIONS or not (user and getattr(user, "is_authenticated", False)):
        return queryset.none()
    if not user.is_active:
        return queryset.none()
    if access is None:
        access = effective_permissions(user)
    granted = access.get((module, action))
    if granted and granted.everything:
        return queryset

    model = queryset.model
    conditions = Q()
    if granted:
        department_field = getattr(model, "RBAC_DEPARTMENT_FIELD", "department_id")
        if granted.departments and department_field:
            conditions |= Q(**{f"{department_field}__in": list(granted.departments)})
        if granted.own:
            for name in getattr(model, "RBAC_OWNER_FIELDS", ("created_by_id",)):
                conditions |= Q(**{name: user.pk})
        if granted.assigned:
            for name in getattr(model, "RBAC_ASSIGNED_FIELDS", ()):
                conditions |= Q(**{name: user.pk})

    content_type = ContentType.objects.get_for_model(model)
    granted_ids = _live_grants(user, action).filter(content_type=content_type).values("object_id")
    conditions |= Q(pk__in=granted_ids)
    return queryset.filter(conditions)


def permissions_payload(access: dict[tuple[str, str], Access]) -> dict[str, dict[str, str]]:
    """Compact form for the frontend: {module: {ACTION: "ALL" | "DEPARTMENT" | ...}}."""
    payload: dict[str, dict[str, str]] = {}
    for (module, action), value in sorted(access.items()):
        if value:
            payload.setdefault(module, {})[action] = value.label
    return payload


# --- Django REST framework integration ------------------------------------------------


def required_action(view, request) -> str | None:
    """The RBAC action a request needs.

    A view may define ``rbac_actions`` (mapping a lower-case HTTP method or, for viewsets,
    the viewset action name to an action) or override ``get_rbac_action(request)``.
    Otherwise the HTTP method decides. Anything unrecognised is denied.
    """
    custom = getattr(view, "get_rbac_action", None)
    if custom:
        return custom(request)
    mapping = getattr(view, "rbac_actions", {})
    method = request.method.lower()
    name = getattr(view, "action", None)
    if name and name in mapping:
        return mapping[name]
    if method in mapping:
        return mapping[method]
    return DEFAULT_ACTION_BY_METHOD.get(request.method)


def request_access(request) -> dict[tuple[str, str], Access]:
    """The user's effective access, computed once per request."""
    cached = getattr(request, "_tcos_access", None)
    if cached is None:
        cached = effective_permissions(request.user)
        request._tcos_access = cached
    return cached


class RBACPermission(BasePermission):
    """Project-wide default permission class.

    A view must declare ``rbac_module``. A view that does not is denied, so forgetting to
    configure permissions fails closed.
    """

    message = "You do not have permission to do this."

    def _allowed(self, request, view, obj=None) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if user.must_change_password:
            self.message = "You must change your password before continuing."
            return False
        module = getattr(view, "rbac_module", None)
        action = required_action(view, request)
        if not module or not action:
            return False
        return can(user, module, action, obj, access=request_access(request))

    def has_permission(self, request, view) -> bool:
        return self._allowed(request, view)

    def has_object_permission(self, request, view, obj) -> bool:
        return self._allowed(request, view, obj)


class ScopedQuerysetMixin:
    """For generic views: only records inside the user's scope exist for them.

    Out-of-scope records return 404 rather than 403, so their existence is not revealed.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        action = required_action(self, self.request)
        if action is None:
            return queryset.none()
        return filter_queryset(
            self.request.user,
            self.rbac_module,
            action,
            queryset,
            access=request_access(self.request),
        )


class ScopedWriteMixin:
    """For generic views: check scope on the record as it WILL be saved.

    ``ScopedQuerysetMixin`` and ``RBACPermission`` check the record as it is now. This
    also checks the new state, so a user cannot create a record outside their scope or
    edit a record so that it leaves their scope (for example, into another department).
    The new record's owner is always the signed-in user; clients cannot choose it.
    """

    def _check_new_state(self, action, candidate):
        if not can(
            self.request.user,
            self.rbac_module,
            action,
            candidate,
            access=request_access(self.request),
        ):
            raise PermissionDenied("You cannot save a record there.", "outside_scope")

    def perform_create(self, serializer):
        model = serializer.Meta.model
        self._check_new_state(
            "CREATE", model(created_by=self.request.user, **serializer.validated_data)
        )
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        candidate = copy.copy(serializer.instance)
        for name, value in serializer.validated_data.items():
            setattr(candidate, name, value)
        self._check_new_state("EDIT", candidate)
        serializer.save()
