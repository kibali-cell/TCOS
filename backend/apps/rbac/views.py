from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.organisation.models import Department

from . import serializers as s
from . import services
from .constants import ACTIONS, MODULES, SCOPES
from .models import Role, UserRole
from .permissions import RBACPermission

# Reading roles needs users.VIEW; changing anything needs users.MANAGE_USERS.
RBAC_ADMIN_ACTIONS = {
    "get": "VIEW",
    "post": "MANAGE_USERS",
    "patch": "MANAGE_USERS",
    "put": "MANAGE_USERS",
    "delete": "MANAGE_USERS",
}


class _UsersModuleView(APIView):
    permission_classes = [RBACPermission]
    rbac_module = "users"
    rbac_actions = RBAC_ADMIN_ACTIONS


class CatalogueView(_UsersModuleView):
    """Modules, actions and scopes that the permission matrix is built from."""

    def get(self, request):
        return Response(
            {
                "modules": [{"code": code, "name": name} for code, name in MODULES],
                "actions": list(ACTIONS),
                "scopes": list(SCOPES),
            }
        )


class RoleListView(_UsersModuleView):
    def get(self, request):
        roles = Role.objects.annotate(
            holders=Count(
                "user_roles", filter=Q(user_roles__revoked_at__isnull=True), distinct=True
            )
        ).order_by("name")
        return Response({"results": [s.role_summary(r, holders=r.holders) for r in roles]})

    def post(self, request):
        data = s.RoleCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        role = services.create_role(
            request.user,
            name=data.validated_data["name"],
            description=data.validated_data.get("description", ""),
            grants=data.validated_data.get("grants", []),
        )
        return Response(s.role_detail(role), status=status.HTTP_201_CREATED)


class RoleDetailView(_UsersModuleView):
    def get(self, request, pk):
        return Response(s.role_detail(get_object_or_404(Role, pk=pk)))

    def patch(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        data = s.RoleWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.update_role(request.user, role, **data.validated_data)
        return Response(s.role_detail(role))

    def delete(self, request, pk):
        services.delete_role(request.user, get_object_or_404(Role, pk=pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoleGrantsView(_UsersModuleView):
    """Replace a role's permission matrix. Takes effect on the very next request."""

    def put(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        data = s.RoleGrantsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.set_role_grants(request.user, role, data.validated_data["grants"])
        return Response(s.role_detail(role))


class UserRoleListView(_UsersModuleView):
    def get(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        rows = (
            UserRole.objects.filter(user=user, revoked_at__isnull=True)
            .select_related("role", "department")
            .order_by("role__name")
        )
        return Response({"results": [s.assignment_payload(r) for r in rows]})

    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        data = s.AssignRoleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        assignment = services.assign_role(
            request.user,
            user,
            data.validated_data["role"],
            department=data.validated_data.get("department"),
            valid_from=data.validated_data.get("valid_from"),
            valid_to=data.validated_data.get("valid_to"),
        )
        return Response(s.assignment_payload(assignment), status=status.HTTP_201_CREATED)


class UserRoleDetailView(_UsersModuleView):
    def delete(self, request, user_id, pk):
        assignment = get_object_or_404(
            UserRole.objects.select_related("role"), pk=pk, user_id=user_id
        )
        services.revoke_user_role(request.user, assignment)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DepartmentListView(_UsersModuleView):
    """Read-only list so role assignments can name a department. Managed from Slice 4."""

    def get(self, request):
        rows = Department.objects.filter(is_active=True)
        return Response(
            {"results": [{"id": str(d.id), "code": d.code, "name": d.name} for d in rows]}
        )


class AccessReviewView(APIView):
    """Who can see which sensitive data, and where it is kept. Needs audit.VIEW (everything)."""

    permission_classes = [RBACPermission]
    rbac_module = "audit"
    rbac_actions = {"get": "VIEW"}

    def get(self, request):
        from apps.audit import events as audit_events
        from apps.audit.service import record as audit

        from .access_review import build_report
        from .permissions import request_access

        granted = request_access(request).get(("audit", "VIEW"))
        if not (granted and granted.everything):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You do not have permission to do this.")
        audit(
            audit_events.ACCESS_REVIEW_VIEWED, actor=request.user, object_type="rbac.AccessReview"
        )
        return Response(build_report())
