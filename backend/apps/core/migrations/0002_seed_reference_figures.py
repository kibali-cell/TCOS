"""The four initial reference figures, unverified (CLAUDE.md rule 8). Repeatable."""

from django.db import migrations

FIGURES = (
    ("total_children", "Total children", 85),
    ("residential_children", "Children in residential care", 42),
    ("outreach_children", "Children in outreach", 43),
    ("total_employees", "Employees", 15),
)


def seed(apps, schema_editor):
    model = apps.get_model("core", "ReferenceFigure")
    for key, label, value in FIGURES:
        model.objects.get_or_create(key=key, defaults={"label": label, "value": value})


def unseed(apps, schema_editor):
    apps.get_model("core", "ReferenceFigure").objects.filter(
        key__in=[k for k, _, _ in FIGURES], is_verified=False
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_reference_figure")]
    operations = [migrations.RunPython(seed, unseed)]
