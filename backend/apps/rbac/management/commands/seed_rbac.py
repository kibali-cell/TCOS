"""Create any missing permissions, default roles and default grants. Safe to re-run.

Existing roles and their grants are never changed, so edits made in the application are kept.
Run after adding a new module to ``apps.rbac.constants.MODULES``.
"""

from django.core.management.base import BaseCommand

from apps.rbac.models import Permission, Role, RolePermission
from apps.rbac.seed import seed


class Command(BaseCommand):
    help = "Seed permissions, default roles and default grants (idempotent)."

    def handle(self, *args, **options):
        created = seed(Permission, Role, RolePermission)
        self.stdout.write(
            "Created {permissions} permissions, {roles} roles, {grants} grants.".format(**created)
        )
