"""The first, PROVISIONAL TZS limits (D-020). Not ratified until a Board Member approves."""

from django.db import migrations

LOW_MAX = 200_000
MEDIUM_MAX = 2_000_000
ALWAYS_HIGH = [
    "ASSET_DISPOSAL",
    "DONOR_REFUND",
    "PAYEE_CHANGE",
    "PAYROLL",
    "STAFF_LOAN",
    "WRITE_OFF",
]


def seed(apps, schema_editor):
    Policy = apps.get_model("approvals", "TzsLimitPolicy")
    if Policy.objects.exists():
        return
    Policy.objects.create(
        version_number=1,
        state="ACTIVE",
        low_max=LOW_MAX,
        medium_max=MEDIUM_MAX,
        always_high=ALWAYS_HIGH,
        reason="Builder's provisional proposal (D-020). Not yet ratified by the Board.",
        is_ratified=False,
    )


def unseed(apps, schema_editor):
    apps.get_model("approvals", "TzsLimitPolicy").objects.filter(
        version_number=1, is_ratified=False, request__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("approvals", "0002_history_triggers")]
    operations = [migrations.RunPython(seed, unseed)]
