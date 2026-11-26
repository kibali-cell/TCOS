"""Who can reach which kind of sensitive data, and where that data is kept (D-070).

Built live from the permission tables, so it can never drift from what is enforced. The
written companion is ``docs/DATA_SOVEREIGNTY.md``.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User

from .models import Role, RolePermission, UserRole
from .permissions import effective_permissions
from .services import role_sensitivity

# (code, label, module, classification, where the data is kept, on devices?)
DATA_CLASSES = (
    ("children", "Child profiles", "children", "CHILD_SENSITIVE"),
    ("welfare", "Social welfare cases", "social_welfare", "CHILD_SENSITIVE"),
    ("medical", "Medical records", "medical", "CHILD_SENSITIVE"),
    ("education", "Education records", "education", "CONFIDENTIAL"),
    ("finance", "Financial records", "finance", "FINANCIAL"),
    ("approvals", "Approval requests", "approvals", "FINANCIAL"),
    ("hr", "Staff personal records", "hr", "STAFF_PERSONAL"),
    ("donors", "Donor records", "donors", "CONFIDENTIAL"),
    ("users", "User accounts and roles", "users", "INTERNAL"),
    ("audit", "Audit log", "audit", "INTERNAL"),
)

STORED = {
    "CHILD_SENSITIVE": "Central PostgreSQL database only. Never copied to phones or computers.",
    "FINANCIAL": "Central PostgreSQL database. Devices may hold only encrypted drafts.",
    "STAFF_PERSONAL": "Central PostgreSQL database only.",
    "CONFIDENTIAL": "Central PostgreSQL database only.",
    "INTERNAL": "Central PostgreSQL database; some reference data is cached encrypted.",
}

OUTSIDE_THE_APPLICATION = (
    "The server operator or hosting provider can reach the database files and backups.",
    "Anyone holding the database owner password can read and change every table.",
    "Backups hold a full copy of all data and need the same care as the live database.",
    "The hash chain on the audit log shows tampering but cannot prevent it by a database "
    "superuser.",
)


def build_report() -> dict:
    today = timezone.localdate()
    users = list(User.objects.filter(status="ACTIVE").order_by("full_name"))
    live = list(
        UserRole.objects.filter(user__in=users, revoked_at__isnull=True, role__is_active=True)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .select_related("role", "department")
    )
    grants: dict = {}
    for role_id, module, action in RolePermission.objects.values_list(
        "role_id", "permission__module", "permission__action"
    ):
        grants.setdefault(role_id, set()).add((module, action))
    roles_of: dict = {}
    for row in live:
        roles_of.setdefault(row.user_id, []).append(row)

    classes = []
    for code, label, module, classification in DATA_CLASSES:
        people = []
        for user in users:
            access = effective_permissions(user).get((module, "VIEW"))
            if not access:
                continue
            via = sorted(
                {
                    row.role.name
                    for row in roles_of.get(user.pk, [])
                    if (module, "VIEW") in grants.get(row.role_id, set())
                }
            )
            people.append(
                {
                    "id": str(user.pk),
                    "name": user.full_name or user.username,
                    "username": user.username,
                    "scope": access.label,
                    "roles": via,
                }
            )
        classes.append(
            {
                "code": code,
                "label": label,
                "module": module,
                "classification": classification,
                "stored": STORED[classification],
                "people": people,
            }
        )

    sensitive_roles = []
    for role in Role.objects.filter(is_active=True).order_by("name"):
        reasons = role_sensitivity(role)
        if reasons:
            sensitive_roles.append(
                {
                    "id": str(role.pk),
                    "name": role.name,
                    "reasons": reasons,
                    "holders": sorted(
                        {r.user.full_name or r.user.username for r in live if r.role_id == role.pk}
                    ),
                }
            )
    region = getattr(settings, "TCOS_HOSTING_REGION", "")
    note = (
        "As set by the server administrator."
        if region
        else "Not set. The hosting region is still an open decision for the owner."
    )
    return {
        "generated_at": timezone.now(),
        "hosting": {"region": region or None, "note": note},
        "classes": classes,
        "sensitive_roles": sensitive_roles,
        "outside_the_application": list(OUTSIDE_THE_APPLICATION),
    }
