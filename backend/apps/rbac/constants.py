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

# --- What counts as a SENSITIVE role (D-044, D-065) ------------------------------------
# A role is sensitive when it can reach confidential data, change who may do what, or make
# binding decisions. Granting one needs a second person's approval (Approval Centre). The
# rule is deliberately simple so it can be read, argued with and changed in one place.
SENSITIVE_MODULES = {
    "administration": "change the organisation, approval routes and settings",
    "children": "see child profiles",
    "social_welfare": "see child welfare cases",
    "medical": "see medical records",
    "finance": "see or change financial records",
    "hr": "see staff personal records",
    "users": "see or manage users and roles",
    "audit": "read the audit log",
}
SENSITIVE_ACTIONS = {
    "MANAGE_USERS": "manage users and roles",
    "DELETE": "delete or archive records",
    "EXPORT": "export data",
}
# APPROVE / REJECT are sensitive unless limited to requests assigned to the person.
DECISION_ACTIONS = ("APPROVE", "REJECT")
