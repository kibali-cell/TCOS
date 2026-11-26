"""Give someone a role from the server console, bypassing the Approval Centre (D-071).

Why it exists: sensitive roles are normally granted through an approval by another person
(D-044), but the very first Board Member or Executive Director cannot be approved by people
who do not exist yet. This command is the one deliberate exception. It needs access to the
server itself, so it belongs to whoever operates the server for the institution, it
requires a written reason, and it is recorded in the audit log.

    python manage.py grant_role_from_console USERNAME ROLE_CODE --reason "..."
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.audit import events as audit_events
from apps.audit.service import record as audit
from apps.rbac.models import Role, UserRole


class Command(BaseCommand):
    help = "Grant a role from the server console (audited). For first-time setup."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("role_code")
        parser.add_argument("--reason", required=True, help="Why this is done outside approval.")

    def handle(self, *args, **options):
        reason = (options["reason"] or "").strip()
        if len(reason) < 10:
            raise CommandError("Give a reason of at least 10 characters.")
        user = User.objects.filter(username=options["username"].lower()).first()
        role = Role.objects.filter(code=options["role_code"].upper(), is_active=True).first()
        if user is None or role is None:
            raise CommandError("Unknown username or role code.")
        with transaction.atomic():
            if UserRole.objects.filter(
                user=user, role=role, department=None, revoked_at__isnull=True
            ).exists():
                raise CommandError("That person already holds this role.")
            assignment = UserRole.objects.create(user=user, role=role)
            audit(
                audit_events.ROLE_ASSIGNED,
                object_type="accounts.User",
                object_id=user.pk,
                metadata={
                    "role": role.code,
                    "assignment_id": assignment.pk,
                    "via": "grant_role_from_console command (no approval)",
                    "reason": reason,
                },
            )
        self.stdout.write(f"{user.username} now holds {role.name}. Recorded in the audit log.")
