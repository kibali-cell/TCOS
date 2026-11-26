"""Check the audit log's hash chain and print its head hash.

Keep the head hash (and its event count) somewhere a database administrator cannot edit,
such as a printed record or another system, and compare it later.
Exit status 1 if the chain is broken.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.audit.service import verify_chain


class Command(BaseCommand):
    help = "Verify the audit log hash chain."

    def handle(self, *args, **options):
        result = verify_chain()
        if not result["ok"]:
            raise CommandError(
                f"AUDIT CHAIN BROKEN at event #{result['broken_at']} "
                f"({result['checked']} earlier events were intact)."
            )
        self.stdout.write(
            f"Audit chain intact: {result['checked']} events. Head hash: {result['head']}"
        )
