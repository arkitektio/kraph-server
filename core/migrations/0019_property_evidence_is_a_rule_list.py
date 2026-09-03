"""Property evidence is a rule list (RFC 0014) — convert the flat lists.

`rule.evidence` on a stored property definition was a flat list of conditions,
all of which had to hold. It is now the definition's rule list shape —
`{"rules": [{"when": [...], "unless": [...]}]}` — so a property can union
rules and carve out exceptions. The conversion is lossless: a list `[c, ...]`
is exactly one rule whose `when` is that list, and reads the same.
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def convert_evidence(evidence):
    """The rule-list form of one stored `evidence` value, or the value untouched.

    A list becomes one rule; a dict already in the rule shape, or None, is
    returned as is. Exposed so the migration test can apply it directly.
    """
    if isinstance(evidence, list):
        return {"rules": [{"when": list(evidence)}]}
    return evidence


def convert(apps, schema_editor):
    Category = apps.get_model("core", "Category")

    converted = []
    for category in Category.objects.exclude(property_definitions=[]).iterator():
        changed = False
        for prop in category.property_definitions or []:
            rule = prop.get("rule") if isinstance(prop, dict) else None
            if isinstance(rule, dict) and isinstance(rule.get("evidence"), list):
                rule["evidence"] = convert_evidence(rule["evidence"])
                changed = True
        if changed:
            converted.append(f"graph #{category.graph_id} category #{category.pk} ({category.key!r})")
            category.save(update_fields=["property_definitions"])
    if converted:
        logger.info("RFC 0014: converted %d flat rule.evidence list(s) to rule lists: %s", len(converted), "; ".join(converted))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_remove_graph_rules_remove_historicalgraph_rules"),
    ]

    operations = [
        migrations.RunPython(convert, migrations.RunPython.noop),
    ]
