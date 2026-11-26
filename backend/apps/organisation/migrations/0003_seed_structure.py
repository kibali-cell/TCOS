"""Seed the proposed starting structure. The reverse is a no-op: it never deletes
departments or positions, which may have been edited or used."""

from django.db import migrations

from apps.organisation.seed import seed


def forwards(apps, schema_editor):
    seed(apps.get_model("organisation", "Department"), apps.get_model("organisation", "Position"))


class Migration(migrations.Migration):
    dependencies = [("organisation", "0002_structure")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
