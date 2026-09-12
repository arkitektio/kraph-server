"""Negative sameness (RFC 0019).

`Link.Kind.DIFFERENT_FROM`: a choices change only, like 0013 — the refs are
opaque and `kind` discriminates.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0013_a_claim_can_cite_the_claims_it_came_from"),
    ]

    operations = [
        migrations.AlterField(
            model_name="link",
            name="kind",
            field=models.CharField(
                choices=[
                    ("informs", "Informs"),
                    ("relation", "Relation"),
                    ("structure_relation", "Structure relation"),
                    ("measurement", "Measurement"),
                    ("participates_as_input", "Participates as input"),
                    ("participates_as_output", "Participates as output"),
                    ("classifies", "Classifies"),
                    ("same_as", "Same as"),
                    ("different_from", "Different from"),
                    ("derived_from", "Derived from"),
                ],
                max_length=32,
            ),
        ),
    ]
