"""The permission catalogue, the 11 default roles and their default grants."""

import importlib

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command

from apps.accounts.models import User
from apps.rbac.constants import ACTIONS, MODULE_CODES
from apps.rbac.models import Permission, Role, RolePermission, UserRole
from apps.rbac.seed import ROLES, seed

from .conftest import PASSWORD

ROLE_CODES = [code for code, _, _ in ROLES]

# The default matrix, written out independently of the seed code on purpose: changing a
# default must be a deliberate edit here too. Format: module -> "ACTION:SCOPE ...".
# Every role also gets approvals CREATE:OWN and VIEW:OWN (except Administrator), and
# approver roles get approvals VIEW/APPROVE/REJECT:ASSIGNED (VIEW is the wider ASSIGNED).
DEFAULT_MATRIX = {
    "BOARD_MEMBER": {
        "administration": "VIEW:ALL",
        "finance": "VIEW:ALL",
        "projects": "VIEW:ALL",
        "donors": "VIEW:ALL",
        "reports": "VIEW:ALL EXPORT:ALL",
        "approvals": "CREATE:OWN VIEW:ASSIGNED APPROVE:ASSIGNED REJECT:ASSIGNED",
    },
    "EXECUTIVE_DIRECTOR": {
        "administration": "VIEW:ALL CREATE:ALL EDIT:ALL",
        "social_welfare": "VIEW:ALL",
        "children": "VIEW:ALL",
        "education": "VIEW:ALL",
        "finance": "VIEW:ALL EXPORT:ALL",
        "projects": "VIEW:ALL",
        "hr": "VIEW:ALL",
        "procurement": "VIEW:ALL",
        "stores": "VIEW:ALL",
        "donors": "VIEW:ALL",
        "reports": "VIEW:ALL EXPORT:ALL",
        "approvals": "CREATE:OWN VIEW:ALL APPROVE:ASSIGNED REJECT:ASSIGNED",
        "audit": "VIEW:ALL",
        "users": "VIEW:ALL",
    },
    "ADMINISTRATOR": {
        "users": "VIEW:ALL CREATE:ALL EDIT:ALL DELETE:ALL MANAGE_USERS:ALL",
        "administration": "VIEW:ALL CREATE:ALL EDIT:ALL DELETE:ALL",
        "audit": "VIEW:ALL",
        "approvals": "VIEW:ALL",
    },
    "SOCIAL_WELFARE_OFFICER": {
        "social_welfare": "VIEW:ALL CREATE:ALL EDIT:ALL",
        "children": "VIEW:ALL CREATE:ALL EDIT:ALL",
        "approvals": "CREATE:OWN VIEW:ASSIGNED APPROVE:ASSIGNED REJECT:ASSIGNED",
    },
    "EDUCATION_OFFICER": {
        "education": "VIEW:ALL CREATE:ALL EDIT:ALL",
        "children": "VIEW:ALL",
        "approvals": "CREATE:OWN VIEW:ASSIGNED APPROVE:ASSIGNED REJECT:ASSIGNED",
    },
    "MEDICAL_OFFICER": {
        "medical": "VIEW:ALL CREATE:ALL EDIT:ALL",
        "children": "VIEW:ALL",
        "approvals": "CREATE:OWN VIEW:ASSIGNED APPROVE:ASSIGNED REJECT:ASSIGNED",
    },
    "FINANCE_OFFICER": {
        "finance": "VIEW:ALL CREATE:ALL EDIT:ALL EXPORT:ALL",
        "donors": "VIEW:ALL",
        "procurement": "VIEW:ALL",
        "reports": "VIEW:ALL EXPORT:ALL",
        "approvals": "CREATE:OWN VIEW:ASSIGNED APPROVE:ASSIGNED REJECT:ASSIGNED",
    },
    "PROJECT_MANAGER": {
        "projects": "VIEW:ALL CREATE:ALL EDIT:ALL",
        "finance": "VIEW:DEPARTMENT",
        "donors": "VIEW:ALL",
        "reports": "VIEW:ALL",
        "approvals": "CREATE:OWN VIEW:ASSIGNED APPROVE:ASSIGNED REJECT:ASSIGNED",
    },
    "STOREKEEPER": {
        "stores": "VIEW:ALL CREATE:ALL EDIT:ALL",
        "procurement": "VIEW:ALL",
        "approvals": "CREATE:OWN VIEW:OWN",
    },
    "PROCUREMENT_OFFICER": {
        "procurement": "VIEW:ALL CREATE:ALL EDIT:ALL",
        "stores": "VIEW:ALL",
        "approvals": "CREATE:OWN VIEW:ASSIGNED APPROVE:ASSIGNED REJECT:ASSIGNED",
    },
    "HR_OFFICER": {
        "hr": "VIEW:ALL CREATE:ALL EDIT:ALL EXPORT:ALL",
        "users": "VIEW:ALL",
        "approvals": "CREATE:OWN VIEW:ASSIGNED APPROVE:ASSIGNED REJECT:ASSIGNED",
    },
}


def expected_cells(code):
    return {
        (module, action): scope
        for module, cells in DEFAULT_MATRIX[code].items()
        for action, scope in (cell.split(":") for cell in cells.split())
    }


def stored_cells(code):
    return {
        (g.permission.module, g.permission.action): g.scope
        for g in RolePermission.objects.filter(role__code=code).select_related("permission")
    }


def test_catalogue_has_every_module_and_action(db):
    assert Permission.objects.count() == len(MODULE_CODES) * len(ACTIONS) == 120
    assert set(Permission.objects.values_list("module", "action")) == {
        (m, a) for m in MODULE_CODES for a in ACTIONS
    }


def test_the_eleven_default_roles_exist_and_are_protected(db):
    assert sorted(Role.objects.values_list("code", flat=True)) == sorted(ROLE_CODES)
    assert len(ROLE_CODES) == 11
    assert Role.objects.filter(is_system=True).count() == 11
    assert not Role.objects.filter(is_active=False).exists()


@pytest.mark.parametrize("code", ROLE_CODES)
def test_default_grants_match_the_reviewed_matrix(db, code):
    assert stored_cells(code) == expected_cells(code)


def test_no_role_has_blanket_access(db):
    """No role may reach every module; the Administrator is broad only over system modules."""
    for code in ROLE_CODES:
        modules = {m for (m, _a) in stored_cells(code)}
        assert modules != set(MODULE_CODES), code
        writable = {
            m
            for (m, a) in stored_cells(code)
            if a in ("CREATE", "EDIT", "DELETE") and m != "approvals"
        }
        assert len(writable) <= 2, (code, writable)  # no role edits across the institution
    admin_modules = {m for (m, _a) in stored_cells("ADMINISTRATOR")}
    assert admin_modules == {"users", "administration", "audit", "approvals"}
    for sensitive in ("children", "medical", "finance", "social_welfare", "hr"):
        assert sensitive not in admin_modules


def test_only_the_administrator_can_manage_users(db):
    holders = {code for code in ROLE_CODES if ("users", "MANAGE_USERS") in stored_cells(code)}
    assert holders == {"ADMINISTRATOR"}


def test_only_the_medical_officer_reads_medical_records(db):
    readers = {code for code in ROLE_CODES if ("medical", "VIEW") in stored_cells(code)}
    assert readers == {"MEDICAL_OFFICER"}


def test_nobody_can_approve_without_the_assigned_scope(db):
    """APPROVE and REJECT are only ever ASSIGNED: the approval chain decides who."""
    for code in ROLE_CODES:
        for (module, action), scope in stored_cells(code).items():
            if action in ("APPROVE", "REJECT"):
                assert scope == "ASSIGNED", (code, module)


def test_seed_is_idempotent(db):
    before = (Permission.objects.count(), Role.objects.count(), RolePermission.objects.count())
    assert seed(Permission, Role, RolePermission) == {"permissions": 0, "roles": 0, "grants": 0}
    call_command("seed_rbac")
    after = (Permission.objects.count(), Role.objects.count(), RolePermission.objects.count())
    assert before == after


def test_reseeding_never_overwrites_edited_roles(db):
    role = Role.objects.get(code="STOREKEEPER")
    role.name = "Store Manager"
    role.save()
    RolePermission.objects.filter(role=role, permission__module="stores").delete()

    call_command("seed_rbac")

    role.refresh_from_db()
    assert role.name == "Store Manager"
    assert not RolePermission.objects.filter(role=role, permission__module="stores").exists()


def test_reseeding_restores_a_deleted_permission_row(db):
    Permission.objects.get(module="donors", action="EXPORT").delete()
    assert call_command("seed_rbac") is None
    assert Permission.objects.filter(module="donors", action="EXPORT").exists()


def test_migration_gives_existing_superusers_the_administrator_role(make_user):
    """Slice 1 admins were superusers. The data migration moves them onto the role."""
    legacy = make_user("legacyadmin", is_superuser=True)
    assert not UserRole.objects.filter(user=legacy).exists()

    migration = importlib.import_module("apps.rbac.migrations.0002_seed_roles_and_permissions")
    migration.forwards(django_apps, None)
    migration.forwards(django_apps, None)  # re-running changes nothing

    assert UserRole.objects.filter(user=legacy, role__code="ADMINISTRATOR").count() == 1
    ordinary = make_user("ordinary")
    migration.forwards(django_apps, None)
    assert not UserRole.objects.filter(user=ordinary).exists()


def test_is_superuser_flag_grants_nothing(make_user):
    from apps.rbac.permissions import can, effective_permissions

    user = make_user("flagonly", is_superuser=True)
    assert effective_permissions(user) == {}
    assert not can(user, "users", "MANAGE_USERS")


def test_create_initial_admin_assigns_the_administrator_role(db, monkeypatch):
    monkeypatch.setenv("TCOS_ADMIN_USERNAME", "root.admin")
    monkeypatch.setenv("TCOS_ADMIN_EMAIL", "root@example.org")
    monkeypatch.setenv("TCOS_ADMIN_FULL_NAME", "Root Admin")
    monkeypatch.setenv("TCOS_ADMIN_PASSWORD", PASSWORD)
    call_command("create_initial_admin")
    user = User.objects.get(username="root.admin")
    assert not user.is_superuser
    assert [r.role.code for r in user.user_roles.all()] == ["ADMINISTRATOR"]
