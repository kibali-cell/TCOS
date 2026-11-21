"""Seed the permission catalogue and the 11 default roles; give existing superusers the
Administrator role.

Idempotent. The reverse is intentionally a no-op: it never deletes roles or assignments,
because they may have been edited or used (never destroy data silently).
"""

from django.db import migrations

from apps.rbac.constants import ADMINISTRATOR_ROLE
from apps.rbac.seed import seed


def forwards(apps, schema_editor):
    Permission = apps.get_model("rbac", "Permission")
    Role = apps.get_model("rbac", "Role")
    RolePermission = apps.get_model("rbac", "RolePermission")
    UserRole = apps.get_model("rbac", "UserRole")
    User = apps.get_model("accounts", "User")

    seed(Permission, Role, RolePermission)

    # Slice 1 made the first administrator a superuser because no roles existed yet.
    # From Slice 2 the flag grants nothing, so those users receive the Administrator role.
    administrator = Role.objects.get(code=ADMINISTRATOR_ROLE)
    for user in User.objects.filter(is_superuser=True):
        UserRole.objects.get_or_create(
            user=user,
            role=administrator,
            department=None,
            revoked_at=None,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("rbac", "0001_initial"),
        ("accounts", "0002_user_department"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
