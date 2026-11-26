"""Approval Centre API (``approvals`` module unless stated).

Every list is scoped: a person sees their own requests, requests in their department scope,
and requests waiting for them. Out-of-scope records answer 404.
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.api import StandardPagination
from apps.organisation.models import Department
from apps.rbac.models import Role
from apps.rbac.permissions import RBACPermission, request_access

from . import limits, services
from . import serializers as s
from .models import ApprovalRequest, Notification, TzsLimitPolicy

APPROVALS_ACTIONS = {"get": "VIEW", "post": "CREATE", "patch": "CREATE"}


class _ApprovalsView(APIView):
    permission_classes = [RBACPermission]
    rbac_module = "approvals"
    rbac_actions = APPROVALS_ACTIONS


def _detail(user, pk) -> ApprovalRequest:
    queryset = services.visible_requests(user).select_related("requester", "department")
    return get_object_or_404(queryset.prefetch_related("assignees__user"), pk=pk)


def _respond(request_row, user, code=status.HTTP_200_OK):
    fresh = _detail(user, request_row.pk)
    return Response(s.request_detail(fresh, user), status=code)


class RequestListView(_ApprovalsView):
    def get(self, request):
        user = request.user
        scope = request.query_params.get("view", "mine")
        if scope == "pending":
            queryset = services.pending_for(user)
        elif scope == "all":
            queryset = services.visible_requests(user)
        else:
            queryset = ApprovalRequest.objects.filter(requester=user)
        params = request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=params["status"].upper())
        if params.get("type"):
            queryset = queryset.filter(request_type=params["type"].upper())
        if params.get("risk"):
            queryset = queryset.filter(risk_level=params["risk"].upper())
        if params.get("search"):
            term = params["search"].strip()
            queryset = queryset.filter(
                Q(title__icontains=term)
                | Q(request_number__icontains=term)
                | Q(requester__full_name__icontains=term)
            )
        queryset = (
            queryset.select_related("requester", "department")
            .prefetch_related("assignees__user")
            .order_by("-created_at")
        )
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=None)
        return paginator.get_paginated_response([s.request_summary(r, user) for r in page])

    def post(self, request):
        data = s.DraftSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        created_id = values.pop("id", None)
        row, created = services.create_draft(request.user, values, request_id=created_id)
        return _respond(row, request.user, 201 if created else 200)


class RequestDetailView(_ApprovalsView):
    def get(self, request, pk):
        return Response(s.request_detail(_detail(request.user, pk), request.user))

    def patch(self, request, pk):
        _detail(request.user, pk)  # 404 for anything out of sight
        data = s.DraftSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.update_draft(request.user, pk, dict(data.validated_data))
        return _respond(ApprovalRequest(pk=pk), request.user)


class _ActionView(_ApprovalsView):
    """POST /requests/<id>/<action>/ ."""

    action_name = ""
    rbac_actions = {"post": "CREATE"}

    def post(self, request, pk):
        _detail(request.user, pk)
        data = s.DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        self.run(request.user, pk, values)
        return _respond(ApprovalRequest(pk=pk), request.user)


class SubmitView(_ActionView):
    def run(self, user, pk, values):
        services.submit(user, pk)


class CancelView(_ActionView):
    def run(self, user, pk, values):
        services.cancel(user, pk, values.get("comment", ""))


class CommentView(_ActionView):
    rbac_actions = {"post": "VIEW"}

    def run(self, user, pk, values):
        services.add_comment(user, pk, values.get("comment", ""))


class ReviewView(_ActionView):
    rbac_actions = {"post": "APPROVE"}

    def run(self, user, pk, values):
        services.review(user, pk, values.get("comment", ""))


class ApproveView(_ActionView):
    rbac_actions = {"post": "APPROVE"}

    def run(self, user, pk, values):
        services.approve(user, pk, values.get("comment", ""), values.get("password"))


class RejectView(_ActionView):
    rbac_actions = {"post": "REJECT"}

    def run(self, user, pk, values):
        services.reject(user, pk, values.get("comment", ""), values.get("password"))


class SummaryView(_ApprovalsView):
    """Numbers for the menu badges."""

    def get(self, request):
        user = request.user
        return Response(
            {
                "pending": services.pending_for(user).count(),
                "unread_notifications": Notification.objects.filter(
                    user=user, read_at__isnull=True
                ).count(),
            }
        )


class NotificationListView(_ApprovalsView):
    rbac_actions = {"get": "VIEW", "post": "VIEW"}

    def get(self, request):
        rows = Notification.objects.filter(user=request.user).order_by("-created_at")
        paginator = StandardPagination()
        page = paginator.paginate_queryset(rows, request, view=None)
        return paginator.get_paginated_response(
            [
                {
                    "id": str(n.pk),
                    "title": n.title,
                    "body": n.body,
                    "request_id": str(n.request_id) if n.request_id else None,
                    "created_at": n.created_at,
                    "is_read": n.read_at is not None,
                }
                for n in page
            ]
        )

    def post(self, request):
        """Mark everything (or the listed ids) read. Only ever touches the caller's own."""
        rows = Notification.objects.filter(user=request.user, read_at__isnull=True)
        ids = request.data.get("ids")
        if isinstance(ids, list):
            rows = rows.filter(pk__in=ids)
        rows.update(read_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoleGrantRequestView(APIView):
    """Ask for a sensitive role for someone else. Needs ``users.MANAGE_USERS``."""

    permission_classes = [RBACPermission]
    rbac_module = "users"
    rbac_actions = {"post": "MANAGE_USERS"}

    def post(self, request):
        data = s.RoleGrantSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        user = get_object_or_404(User, pk=values["user"])
        role = get_object_or_404(Role, pk=values["role"])
        department = (
            get_object_or_404(Department, pk=values["department"])
            if values.get("department")
            else None
        )
        row = services.request_role_grant(
            request.user,
            user=user,
            role=role,
            reason=values["reason"],
            department=department,
            valid_from=values.get("valid_from"),
            valid_to=values.get("valid_to"),
        )
        fresh = ApprovalRequest.objects.get(pk=row.pk)
        return Response(s.request_detail(fresh, request.user), status=status.HTTP_201_CREATED)


class TzsLimitsView(_ApprovalsView):
    """The limits in force, their history, and any proposal waiting for approval."""

    def get(self, request):
        policies = list(TzsLimitPolicy.objects.select_related("ratified_by"))
        active = next((p for p in policies if p.state == "ACTIVE"), None)
        pending = next((p for p in policies if p.state == "PROPOSED"), None)
        return Response(
            {
                "active": s.policy_payload(active) if active else None,
                "pending": s.policy_payload(pending) if pending else None,
                "history": [s.policy_payload(p) for p in policies],
                "kinds": [{"code": k, "label": v} for k, v in limits.ALWAYS_HIGH_KINDS.items()],
                "explanation": limits.LIMITS_EXPLANATION,
                "can_propose": bool(
                    request_access(request).get(("administration", "EDIT"))
                    and request_access(request)[("administration", "EDIT")].everything
                ),
            }
        )


class TzsProposeView(APIView):
    """Propose new limits. Needs ``administration.EDIT``; takes effect only once approved."""

    permission_classes = [RBACPermission]
    rbac_module = "administration"
    rbac_actions = {"post": "EDIT"}

    def post(self, request):
        data = s.TzsProposalSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = services.propose_tzs_limits(request.user, **data.validated_data)
        fresh = ApprovalRequest.objects.get(pk=row.pk)
        return Response(s.request_detail(fresh, request.user), status=status.HTTP_201_CREATED)
