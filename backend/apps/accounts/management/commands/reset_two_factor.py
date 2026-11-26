"""Remove a person's two-factor set-up from the server console (lost phone, no recovery codes).

The only way to do this for someone who holds a sensitive role. It needs the server itself
and a written reason, and is audited.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.accounts import twofactor
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Remove a user's two-factor set-up (server console only)."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--reason", required=True, help="Why (kept in the audit log).")

    def handle(self, *args, username, reason, **options):
        user = User.objects.filter(username=username.strip().lower()).first()
        if user is None:
            raise CommandError("No such user.")
        if not reason.strip():
            raise CommandError("A reason is required.")
        twofactor.reset_for(None, user, reason)
        self.stdout.write(f"Two-factor set-up removed for {user.username}. Sessions ended.")
