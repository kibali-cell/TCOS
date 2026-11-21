"""Idempotent seed of the permission catalogue, the 11 default roles and their default grants.

SAFE TO RE-RUN: missing permissions and roles are created; an existing role's grants are
never touched, so edits made in the application survive. Works with real or historical
(migration) models, which are passed in.

The default grants below are a proposal for the owner's review (docs/DECISIONS.md D-034).
No role has blanket access. Only the Administrator is broad, and only over system modules.
"""

from .constants import ACTIONS, ADMINISTRATOR_ROLE, MODULE_CODES, MODULES

ROLES = (
    ("BOARD_MEMBER", "Board Member", "Governance oversight; approves at board level."),
    (
        "EXECUTIVE_DIRECTOR",
        "Executive Director",
        "Oversees all operations except individual medical records.",
    ),
    (
        ADMINISTRATOR_ROLE,
        "Administrator",
        "Manages users, roles and settings. No welfare, medical or financial records.",
    ),
    ("SOCIAL_WELFARE_OFFICER", "Social Welfare Officer", "Child welfare and child profiles."),
    ("EDUCATION_OFFICER", "Education Officer", "Education records; reads child profiles."),
    ("MEDICAL_OFFICER", "Medical Officer", "Medical records; reads child profiles."),
    ("FINANCE_OFFICER", "Finance Officer", "Financial records, donor and report views."),
    ("PROJECT_MANAGER", "Project Manager", "Projects; reads finance of own department."),
    ("STOREKEEPER", "Storekeeper", "Stores and inventory."),
    ("PROCUREMENT_OFFICER", "Procurement Officer", "Procurement; reads stores."),
    ("HR_OFFICER", "HR Officer", "Staff records; reads the user list."),
)

_APPROVER_ROLES = {
    "BOARD_MEMBER",
    "EXECUTIVE_DIRECTOR",
    "SOCIAL_WELFARE_OFFICER",
    "EDUCATION_OFFICER",
    "MEDICAL_OFFICER",
    "FINANCE_OFFICER",
    "PROJECT_MANAGER",
    "PROCUREMENT_OFFICER",
    "HR_OFFICER",
}

# role -> list of (module, "ACTION ACTION", scope)
_GRANTS = {
    "BOARD_MEMBER": [
        ("administration", "VIEW", "ALL"),
        ("finance", "VIEW", "ALL"),
        ("projects", "VIEW", "ALL"),
        ("donors", "VIEW", "ALL"),
        ("reports", "VIEW EXPORT", "ALL"),
    ],
    "EXECUTIVE_DIRECTOR": [
        ("administration", "VIEW CREATE EDIT", "ALL"),
        ("social_welfare", "VIEW", "ALL"),
        ("children", "VIEW", "ALL"),
        ("education", "VIEW", "ALL"),
        ("finance", "VIEW EXPORT", "ALL"),
        ("projects", "VIEW", "ALL"),
        ("hr", "VIEW", "ALL"),
        ("procurement", "VIEW", "ALL"),
        ("stores", "VIEW", "ALL"),
        ("donors", "VIEW", "ALL"),
        ("reports", "VIEW EXPORT", "ALL"),
        ("approvals", "VIEW", "ALL"),
        ("audit", "VIEW", "ALL"),
        ("users", "VIEW", "ALL"),
    ],
    ADMINISTRATOR_ROLE: [
        ("users", "VIEW CREATE EDIT DELETE MANAGE_USERS", "ALL"),
        ("administration", "VIEW CREATE EDIT DELETE", "ALL"),
        ("audit", "VIEW", "ALL"),
        ("approvals", "VIEW", "ALL"),
    ],
    "SOCIAL_WELFARE_OFFICER": [
        ("social_welfare", "VIEW CREATE EDIT", "ALL"),
        ("children", "VIEW CREATE EDIT", "ALL"),
    ],
    "EDUCATION_OFFICER": [
        ("education", "VIEW CREATE EDIT", "ALL"),
        ("children", "VIEW", "ALL"),
    ],
    "MEDICAL_OFFICER": [
        ("medical", "VIEW CREATE EDIT", "ALL"),
        ("children", "VIEW", "ALL"),
    ],
    "FINANCE_OFFICER": [
        ("finance", "VIEW CREATE EDIT EXPORT", "ALL"),
        ("donors", "VIEW", "ALL"),
        ("procurement", "VIEW", "ALL"),
        ("reports", "VIEW EXPORT", "ALL"),
    ],
    "PROJECT_MANAGER": [
        ("projects", "VIEW CREATE EDIT", "ALL"),
        ("finance", "VIEW", "DEPARTMENT"),
        ("donors", "VIEW", "ALL"),
        ("reports", "VIEW", "ALL"),
    ],
    "STOREKEEPER": [
        ("stores", "VIEW CREATE EDIT", "ALL"),
        ("procurement", "VIEW", "ALL"),
    ],
    "PROCUREMENT_OFFICER": [
        ("procurement", "VIEW CREATE EDIT", "ALL"),
        ("stores", "VIEW", "ALL"),
    ],
    "HR_OFFICER": [
        ("hr", "VIEW CREATE EDIT EXPORT", "ALL"),
        ("users", "VIEW", "ALL"),
    ],
}


_RANK = {"OWN": 0, "ASSIGNED": 1, "DEPARTMENT": 2, "ALL": 3}


def default_grants(role_code: str) -> list[tuple[str, str, str]]:
    """(module, action, scope) for a role: one scope per permission, the widest listed.

    ASSIGNED already includes OWN (see apps.rbac.permissions).
    """
    wanted = [
        (module, action, scope)
        for module, actions, scope in _GRANTS.get(role_code, [])
        for action in actions.split()
    ]
    if role_code != ADMINISTRATOR_ROLE:  # anyone may raise and see their own requests
        wanted += [("approvals", "CREATE", "OWN"), ("approvals", "VIEW", "OWN")]
    if role_code in _APPROVER_ROLES:  # decide requests assigned to them (chain enforced in Slice 5)
        wanted += [("approvals", action, "ASSIGNED") for action in ("VIEW", "APPROVE", "REJECT")]

    best: dict[tuple[str, str], str] = {}
    for module, action, scope in wanted:
        key = (module, action)
        if key not in best or _RANK[scope] > _RANK[best[key]]:
            best[key] = scope
    return [(module, action, scope) for (module, action), scope in best.items()]


def seed(Permission, Role, RolePermission) -> dict:
    """Create what is missing. Returns counts of what was created."""
    created = {"permissions": 0, "roles": 0, "grants": 0}

    labels = dict(MODULES)
    permissions = {}
    for module in MODULE_CODES:
        for action in ACTIONS:
            permission, was_created = Permission.objects.get_or_create(
                module=module,
                action=action,
                defaults={"description": f"{action.replace('_', ' ').title()} in {labels[module]}"},
            )
            permissions[(module, action)] = permission
            created["permissions"] += was_created

    for code, name, description in ROLES:
        role, was_created = Role.objects.get_or_create(
            code=code, defaults={"name": name, "description": description, "is_system": True}
        )
        if not was_created:
            continue  # never overwrite an existing role or its edited grants
        created["roles"] += 1
        for module, action, scope in default_grants(code):
            RolePermission.objects.create(
                role=role, permission=permissions[(module, action)], scope=scope
            )
            created["grants"] += 1
    return created
