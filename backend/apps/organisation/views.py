"""Organisation API. Every endpoint needs the ``administration`` permission at ALL scope.

Reading needs VIEW; creating needs CREATE; changing, assigning and chains need EDIT;
archiving needs DELETE (archiving is the only form of deletion). Structure is
institution-wide, so a department-limited grant is not enough.
"""

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.api import StandardPagination
from apps.rbac.models import Role
from apps.rbac.permissions import RBACPermission, request_access, required_action

from . import serializers as s
from . import services
from .models import ApprovalHierarchy, Department, Position, StaffAssignment


class OrganisationPermission(RBACPermission):
    """RBAC for the administration module, and only with institution-wide (ALL) scope."""

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        granted = request_access(request).get((view.rbac_module, required_action(view, request)))
        return bool(granted and granted.everything)


class _OrgView(APIView):
    permission_classes = [OrganisationPermission]
    rbac_module = "administration"
    rbac_actions = {"get": "VIEW", "post": "CREATE", "patch": "EDIT", "put": "EDIT"}


def _flag(request, name, default=False) -> bool:
    value = request.query_params.get(name)
    return default if value is None else value.lower() in {"1", "true", "yes"}


def _page(request, queryset, shape):
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request, view=None)
    return paginator.get_paginated_response([shape(row) for row in page])


# --- Overview -----------------------------------------------------------------------------


class TreeView(_OrgView):
    """The whole structure as a tree (bounded in size, so it is not paged)."""

    def get(self, request):
        tree = services.organisation_tree(include_archived=_flag(request, "include_archived"))
        return Response({"results": tree})


class OptionsView(_OrgView):
    """Choices the screens need: roles that can approve, approver kinds, limits."""

    def get(self, request):
        roles = Role.objects.filter(is_active=True).order_by("name")
        return Response(
            {
                "roles": [s.role_option(role) for role in roles],
                "approver_types": [
                    {"value": value, "label": label}
                    for value, label in ApprovalHierarchy.ApproverType.choices
                ],
                "default_request_type": "DEFAULT",
                "max_chain_steps": services.MAX_CHAIN_STEPS,
            }
        )


class PeopleView(_OrgView):
    """Names only, to pick someone for an assignment, a head or an approver."""

    def get(self, request):
        people = User.objects.filter(status=User.Status.ACTIVE).order_by("full_name", "username")
        q = (request.query_params.get("q") or "").strip()
        if q:
            people = people.filter(Q(full_name__icontains=q) | Q(username__icontains=q))
        return _page(request, people, s._person)


# --- Departments -----------------------------------------------------------------------------


def _departments():
    return Department.objects.select_related("parent", "head").annotate(
        staff_count=Count(
            "staff_assignments__user",
            filter=Q(staff_assignments__end_date__isnull=True),
            distinct=True,
        ),
        position_count=Count("positions", filter=Q(positions__is_archived=False), distinct=True),
    )


class DepartmentListView(_OrgView):
    def get(self, request):
        rows = _departments()
        archived = (request.query_params.get("archived") or "false").lower()
        if archived == "false":
            rows = rows.filter(is_archived=False)
        elif archived == "true":
            rows = rows.filter(is_archived=True)
        q = (request.query_params.get("q") or "").strip()
        if q:
            rows = rows.filter(Q(name__icontains=q) | Q(code__icontains=q))
        parent = request.query_params.get("parent")
        if parent == "none":
            rows = rows.filter(parent__isnull=True)
        elif parent:
            rows = rows.filter(parent_id=parent)
        return _page(request, rows.order_by("name"), s.department_payload)

    def post(self, request):
        data = s.DepartmentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        department = services.create_department(request.user, **data.validated_data)
        row = _departments().get(pk=department.pk)
        return Response(s.department_payload(row), status=status.HTTP_201_CREATED)


class DepartmentDetailView(_OrgView):
    def _row(self, pk):
        return get_object_or_404(_departments(), pk=pk)

    def get(self, request, pk):
        row = self._row(pk)
        return Response(s.department_payload(row, blockers=services.department_blockers(row)))

    def patch(self, request, pk):
        row = self._row(pk)
        data = s.DepartmentUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        services.update_department(request.user, row, **data.validated_data)
        row = self._row(pk)
        return Response(s.department_payload(row, blockers=services.department_blockers(row)))


class DepartmentHeadView(_OrgView):
    def put(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        data = s.HeadSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.set_department_head(request.user, department, data.validated_data["user"])
        row = get_object_or_404(_departments(), pk=pk)
        return Response(s.department_payload(row))


class DepartmentArchiveView(_OrgView):
    rbac_actions = {"post": "DELETE"}

    def post(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        data = s.ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.archive_department(
            request.user, department, reason=data.validated_data.get("reason", "")
        )
        return Response(s.department_payload(get_object_or_404(_departments(), pk=pk)))


class DepartmentRestoreView(_OrgView):
    rbac_actions = {"post": "EDIT"}

    def post(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        services.restore_department(request.user, department)
        return Response(s.department_payload(get_object_or_404(_departments(), pk=pk)))


# --- Approval chains --------------------------------------------------------------------------


class DepartmentChainsView(_OrgView):
    def get(self, request, pk):
        department = get_object_or_404(Department, pk=pk)
        steps = ApprovalHierarchy.objects.filter(department=department).select_related(
            "approver_position", "approver_role", "approver_user"
        )
        chains: dict[str, list] = {}
        for step in steps.order_by("request_type", "step_order"):
            chains.setdefault(step.request_type, []).append(s.step_payload(step))
        return Response({"chains": chains})


class DepartmentChainDetailView(_OrgView):
    def put(self, request, pk, request_type):
        department = get_object_or_404(Department, pk=pk)
        data = s.ChainSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        steps = [
            {key: (str(value) if value else None) for key, value in step.items()}
            for step in data.validated_data["steps"]
        ]
        result = services.set_approval_chain(request.user, department, request_type, steps)
        return Response(
            {"request_type": request_type.upper(), "steps": [s.step_payload(x) for x in result]}
        )


# --- Positions ---------------------------------------------------------------------------------


def _positions():
    return Position.objects.select_related("department", "reports_to__department").annotate(
        holder_count=Count(
            "assignments", filter=Q(assignments__end_date__isnull=True), distinct=True
        )
    )


class PositionListView(_OrgView):
    def get(self, request):
        rows = _positions()
        archived = (request.query_params.get("archived") or "false").lower()
        if archived == "false":
            rows = rows.filter(is_archived=False)
        elif archived == "true":
            rows = rows.filter(is_archived=True)
        department = request.query_params.get("department")
        if department:
            rows = rows.filter(department_id=department)
        q = (request.query_params.get("q") or "").strip()
        if q:
            rows = rows.filter(title__icontains=q)
        return _page(request, rows.order_by("department__name", "title"), s.position_payload)

    def post(self, request):
        data = s.PositionCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        position = services.create_position(request.user, **data.validated_data)
        return Response(
            s.position_payload(get_object_or_404(_positions(), pk=position.pk)),
            status=status.HTTP_201_CREATED,
        )


class PositionDetailView(_OrgView):
    def _row(self, pk):
        return get_object_or_404(_positions(), pk=pk)

    def get(self, request, pk):
        row = self._row(pk)
        return Response(s.position_payload(row, blockers=services.position_blockers(row)))

    def patch(self, request, pk):
        row = self._row(pk)
        data = s.PositionUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        services.update_position(request.user, row, **data.validated_data)
        row = self._row(pk)
        return Response(s.position_payload(row, blockers=services.position_blockers(row)))


class PositionArchiveView(_OrgView):
    rbac_actions = {"post": "DELETE"}

    def post(self, request, pk):
        position = get_object_or_404(Position, pk=pk)
        data = s.ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.archive_position(
            request.user, position, reason=data.validated_data.get("reason", "")
        )
        return Response(s.position_payload(get_object_or_404(_positions(), pk=pk)))


class PositionRestoreView(_OrgView):
    rbac_actions = {"post": "EDIT"}

    def post(self, request, pk):
        position = get_object_or_404(Position, pk=pk)
        services.restore_position(request.user, position)
        return Response(s.position_payload(get_object_or_404(_positions(), pk=pk)))


# --- Staff assignments -------------------------------------------------------------------------


def _assignments():
    return StaffAssignment.objects.select_related(
        "user", "position", "department", "reports_to_user"
    )


class AssignmentListView(_OrgView):
    def get(self, request):
        rows = _assignments()
        params = request.query_params
        current = (params.get("current") or "true").lower()
        if current == "true":
            rows = rows.filter(end_date__isnull=True)
        elif current == "false":
            rows = rows.filter(end_date__isnull=False)
        for name, field in (
            ("user", "user_id"),
            ("department", "department_id"),
            ("position", "position_id"),
        ):
            if params.get(name):
                rows = rows.filter(**{field: params[name]})
        q = (params.get("q") or "").strip()
        if q:
            rows = rows.filter(Q(user__full_name__icontains=q) | Q(user__username__icontains=q))
        return _page(request, rows.order_by("user__full_name", "-start_date"), s.assignment_payload)

    def post(self, request):
        data = s.AssignmentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        assignment = services.assign_staff(
            request.user,
            values.pop("user"),
            values.pop("position"),
            is_primary=values.get("is_primary"),
            reports_to_user=values.get("reports_to_user"),
            start_date=values.get("start_date"),
        )
        row = get_object_or_404(_assignments(), pk=assignment.pk)
        return Response(s.assignment_payload(row), status=status.HTTP_201_CREATED)


class AssignmentDetailView(_OrgView):
    def get(self, request, pk):
        return Response(s.assignment_payload(get_object_or_404(_assignments(), pk=pk)))

    def patch(self, request, pk):
        assignment = get_object_or_404(StaffAssignment, pk=pk)
        data = s.AssignmentUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.set_reports_to_user(
            request.user, assignment, data.validated_data["reports_to_user"]
        )
        return Response(s.assignment_payload(get_object_or_404(_assignments(), pk=pk)))


class _AssignmentAction(_OrgView):
    rbac_actions = {"post": "EDIT"}


class AssignmentEndView(_AssignmentAction):
    def post(self, request, pk):
        assignment = get_object_or_404(StaffAssignment, pk=pk)
        data = s.EndAssignmentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.end_assignment(
            request.user, assignment, end_date=data.validated_data.get("end_date")
        )
        return Response(s.assignment_payload(get_object_or_404(_assignments(), pk=pk)))


class AssignmentTransferView(_AssignmentAction):
    def post(self, request, pk):
        assignment = get_object_or_404(StaffAssignment, pk=pk)
        data = s.TransferSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        created = services.transfer_staff(request.user, assignment, data.validated_data["position"])
        return Response(
            s.assignment_payload(get_object_or_404(_assignments(), pk=created.pk)),
            status=status.HTTP_201_CREATED,
        )


class AssignmentMakePrimaryView(_AssignmentAction):
    def post(self, request, pk):
        assignment = get_object_or_404(StaffAssignment, pk=pk)
        services.make_primary(request.user, assignment)
        return Response(s.assignment_payload(get_object_or_404(_assignments(), pk=pk)))
