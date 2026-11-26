"""Shared setup for the Approval Centre tests."""

from apps.approvals import services
from apps.organisation.models import ApprovalHierarchy, Department
from apps.rbac.models import Role

BASE = "/api/v1/approvals/"


def url(*parts):
    return BASE + "/".join(str(p) for p in parts) + "/"


def chain(department, *steps, request_type="DEFAULT"):
    """steps: ("DEPARTMENT_HEAD",) or ("ROLE", role_code)."""
    for order, spec in enumerate(steps, start=1):
        kind = spec[0]
        kwargs = {}
        if kind == "ROLE":
            kwargs["approver_role"] = Role.objects.get(code=spec[1])
        ApprovalHierarchy.objects.create(
            department=department,
            request_type=request_type,
            step_order=order,
            approver_type=kind,
            **kwargs,
        )


def new_department(code="FIN-X", name="Finance X"):
    return Department.objects.create(code=code, name=name)


def draft_and_submit(user, **overrides):
    data = {"title": "Buy school books", "description": "Term 1", "amount_tzs": 150_000}
    data.update(overrides)
    row, _ = services.create_draft(user, data)
    return services.submit(user, row.pk)
