from django.db import migrations, models
from django.db.models import Q


def backfill_opportunity_identifiers(apps, schema_editor):
    Opportunity = apps.get_model("opportunities", "Opportunity")
    OpportunityIdentifierSequence = apps.get_model("opportunities", "OpportunityIdentifierSequence")

    opportunities = list(
        Opportunity.objects.filter(Q(identifier__isnull=True) | Q(identifier="")).order_by("created_at", "id")
    )
    if not opportunities:
        return

    sequences = {}

    for opp in opportunities:
        year = opp.created_at.year if getattr(opp, "created_at", None) else 2026
        if year not in sequences:
            seq_record = OpportunityIdentifierSequence.objects.filter(year=year).first()
            if seq_record:
                sequences[year] = seq_record.next_value
            else:
                sequences[year] = 1

        seq_val = sequences[year]
        ident = f"OPP-{year:04d}-{seq_val:06d}"
        Opportunity.objects.filter(id=opp.id).update(identifier=ident)
        sequences[year] = seq_val + 1

    for year, next_val in sequences.items():
        OpportunityIdentifierSequence.objects.update_or_create(
            year=year,
            defaults={"next_value": next_val},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("opportunities", "0002_opportunity"),
    ]

    operations = [
        migrations.CreateModel(
            name="OpportunityIdentifierSequence",
            fields=[
                ("year", models.PositiveIntegerField(help_text="Calendar year for which sequence numbers are allocated.", primary_key=True, serialize=False)),
                ("next_value", models.PositiveBigIntegerField(default=1, help_text="The next available sequence number for this calendar year.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Opportunity Identifier Sequence",
                "verbose_name_plural": "Opportunity Identifier Sequences",
            },
        ),
        migrations.AddField(
            model_name="opportunity",
            name="identifier",
            field=models.CharField(
                blank=True,
                help_text="Human-readable immutable opportunity identifier (e.g. OPP-2026-000124).",
                max_length=32,
                null=True,
            ),
        ),
        migrations.RunPython(
            backfill_opportunity_identifiers,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="opportunity",
            name="identifier",
            field=models.CharField(
                editable=False,
                help_text="Human-readable immutable opportunity identifier (e.g. OPP-2026-000124).",
                max_length=32,
                unique=True,
            ),
        ),
    ]
