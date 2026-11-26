"""User management API (Slice 6). Reading needs users.VIEW; every change needs
users.MANAGE_USERS. Nobody is ever hard-deleted: accounts are deactivated.

Roles are given and removed through ``/api/v1/rbac/users/<id>/roles/`` (sensitive roles only
via the Approval Centre). Department and position follow the person's main staff
assignment (organisation screen).
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api import StandardPagination
from apps.organisation.models import StaffAssignment
from apps.rbac.models import UserRole
from apps.rbac.permissions import RBACPermission, filter_queryset, request_access

from . import recovery, services, twofactor
from .models import User

SORT_FIELDS = {
    "full_name": "full_name",
    "username": "username",
    "email": "email",
    "status": "status",
    "created_at": "created_at",
    "last_login": "last_login",
}


class UserWriteSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    full_name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=32, allow_blank=True, required=False, default="")


class UserEditSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254, required=False)
    full_name = serializers.CharField(max_length=200, required=False)
    phone = serializers.CharField(max_length=32, allow_blank=True, required=False)


class StatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=User.Status.values)
    reason = serializers.CharField(max_length=300, allow_blank=True, required=False, default="")


def _live_roles(user_ids):
    today = timezone.localdate()
    rows = (
        UserRole.objects.filter(user_id__in=user_ids, revoked_at__isnull=True, role__is_active=True)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .select_related("role", "department")
        .order_by("role__name")
    )
    result: dict = {}
    for row in rows:
        result.setdefault(row.user_id, []).append(
            {
                "id": str(row.pk),
                "role_id": str(row.role_id),
                "name": row.role.name,
                "department": row.department.name if row.department else None,
            }
        )
    return result


def _main_positions(user_ids):
    rows = StaffAssignment.objects.filter(
        user_id__in=user_ids, end_date__isnull=True, is_primary=True
    ).select_related("position")
    return {row.user_id: row.position.title for row in rows}


def _row(user: User, roles, positions) -> dict:
    return {
        "id": str(user.pk),
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "status": user.status,
        "department": (
            {"id": str(user.department_id), "name": user.department.name}
            if user.department_id
            else None
        ),
        "position": positions.get(user.pk),
        "roles": roles.get(user.pk, []),
        "created_at": user.created_at,
        "last_login": user.last_login,
        "must_change_password": user.must_change_password,
    }


class _UserView(APIView):
    permission_classes = [RBACPermission]
    rbac_module = "users"
    rbac_actions = {"get": "VIEW", "post": "MANAGE_USERS", "patch": "MANAGE_USERS"}

    def scoped(self, request, action):
        return filter_queryset(
            request.user,
            "users",
            action,
            User.objects.select_related("department"),
            access=request_access(request),
        )

    def target(self, request, pk, action):
        return get_object_or_404(self.scoped(request, action), pk=pk)


class UserListView(_UserView):
    def get(self, request):
        queryset = self.scoped(request, "VIEW")
        params = request.query_params
        term = (params.get("q") or "").strip()
        if term:
            queryset = queryset.filter(
                Q(full_name__icontains=term)
                | Q(username__icontains=term.lower())
                | Q(email__icontains=term.lower())
            )
        if params.get("status") in User.Status.values:
            queryset = queryset.filter(status=params["status"])
        if params.get("department"):
            try:
                queryset = queryset.filter(department_id=params["department"])
            except Exception:  # noqa: BLE001 - a malformed id simply matches nothing
                queryset = queryset.none()
        if params.get("role"):
            today = timezone.localdate()
            held = UserRole.objects.filter(role_id=params["role"], revoked_at__isnull=True).filter(
                Q(valid_to__isnull=True) | Q(valid_to__gte=today)
            )
            queryset = queryset.filter(pk__in=held.values("user_id"))
        ordering = params.get("ordering") or "full_name"
        descending = ordering.startswith("-")
        field = SORT_FIELDS.get(ordering.lstrip("-"), "full_name")
        queryset = queryset.order_by(f"{'-' if descending else ''}{field}", "id")
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        ids = [u.pk for u in page]
        roles, positions = _live_roles(ids), _main_positions(ids)
        return paginator.get_paginated_response([_row(u, roles, positions) for u in page])

    def post(self, request):
        data = UserWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user, temporary = services.admin_create_user(request.user, **data.validated_data)
        body = _row(user, {}, {})
        body["temporary_password"] = temporary  # shown once; never stored or logged
        return Response(body, status=status.HTTP_201_CREATED)


class UserDetailView(_UserView):
    def get(self, request, pk):
        user = self.target(request, pk, "VIEW")
        body = _row(user, _live_roles([user.pk]), _main_positions([user.pk]))
        body["two_factor"] = twofactor.status_payload(user)
        return Response(body)

    def patch(self, request, pk):
        user = self.target(request, pk, "MANAGE_USERS")
        data = UserEditSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.update_user(request.user, user, **data.validated_data)
        return Response(_row(user, _live_roles([user.pk]), _main_positions([user.pk])))


class UserStatusView(_UserView):
    def post(self, request, pk):
        user = self.target(request, pk, "MANAGE_USERS")
        data = StatusSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.set_user_status(
            request.user, user, data.validated_data["status"], data.validated_data["reason"]
        )
        return Response(_row(user, _live_roles([user.pk]), _main_positions([user.pk])))


class UserUnlockView(_UserView):
    def post(self, request, pk):
        user = self.target(request, pk, "MANAGE_USERS")
        services.unlock_user(request.user, user)
        return Response(_row(user, _live_roles([user.pk]), _main_positions([user.pk])))


class UserSendResetLinkView(_UserView):
    """E-mail the person a link to choose their own password. Nobody else sees a password."""

    def post(self, request, pk):
        user = self.target(request, pk, "MANAGE_USERS")
        recovery.admin_send_link(request.user, user)
        return Response({"detail": f"A reset link has been sent to {user.email}."})


class UserResetTwoFactorView(_UserView):
    def post(self, request, pk):
        user = self.target(request, pk, "MANAGE_USERS")
        reason = str(request.data.get("reason", ""))[:300]
        twofactor.reset_for(request.user, user, reason)
        return Response(_row(user, _live_roles([user.pk]), _main_positions([user.pk])))
