from django.core.management.base import BaseCommand

from apps.organisation.models import Department, Position
from apps.organisation.seed import seed


class Command(BaseCommand):
    help = "Create any missing starting departments and head positions (never overwrites edits)."

    def handle(self, *args, **options):
        created = seed(Department, Position)
        self.stdout.write(f"Created {created} department(s).")
