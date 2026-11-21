"""Modules, actions and scopes. Single source of truth for the RBAC catalogue."""

ACTIONS = (
    "VIEW",
    "CREATE",
    "EDIT",
    "DELETE",
    "APPROVE",
    "REJECT",
    "EXPORT",
    "MANAGE_USERS",
)

ALL = "ALL"
DEPARTMENT = "DEPARTMENT"
OWN = "OWN"
ASSIGNED = "ASSIGNED"
SCOPES = (ALL, DEPARTMENT, OWN, ASSIGNED)

# (code, label). Later phases append here and re-run `seed_rbac`.
MODULES = (
    ("administration", "Institutional Administration"),
    ("social_welfare", "Social Welfare Management"),
    ("children", "Child Profile Management"),
    ("education", "Education Management"),
    ("medical", "Medical Management"),
    ("finance", "Financial Management"),
    ("projects", "Project Management"),
    ("hr", "Human Resources"),
    ("procurement", "Procurement"),
    ("stores", "Stores and Inventory"),
    ("donors", "Donor Management"),
    ("reports", "Reports and Analytics"),
    ("approvals", "Approval Centre"),
    ("audit", "Audit Log"),
    ("users", "Users, Roles and Permissions"),
)
MODULE_CODES = tuple(code for code, _ in MODULES)

ADMINISTRATOR_ROLE = "ADMINISTRATOR"
