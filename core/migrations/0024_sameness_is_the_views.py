"""Sameness trust is the view's, not a category's (RFC 0024).

`Graph.sameness_rule` is where whose merges count is decided. A category
definition may no longer name `KIND SAMENESS`: a per-category answer to "are
these one thing" could give one view two contradictory individuals for one
pair of nodes. Stored definitions are rewritten losslessly for everything
else — a `KIND NOT_IN [SAMENESS, ...]` carve-out loses the SAMENESS entry (and
the condition, if that was all it excluded); a rule that covered SAMENESS
*only* is dropped, because it governed nothing a category still governs.
The graph's `sameness_rule` starts empty — everyone — which is what a
primitive category trusted before.
"""

import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)

SAMENESS = "SAMENESS"
EVERY_OTHER_KIND = ["CLASSIFICATION", "EXISTENCE", "EVIDENCE", "MEASUREMENT"]


def _covers_only_sameness(rule: dict) -> bool:
    for condition in rule.get("when") or []:
        if not isinstance(condition, dict) or condition.get("field") != "KIND":
            continue
        operator, value = condition.get("operator"), condition.get("value")
        values = [value] if isinstance(value, str) else list(value or [])
        if operator == "IS" and value == SAMENESS:
            return True
        if operator == "IN" and values == [SAMENESS]:
            return True
    return False


def _strip_sameness(rule: dict) -> dict | None:
    if _covers_only_sameness(rule):
        return None
    when = []
    for condition in rule.get("when") or []:
        if isinstance(condition, dict) and condition.get("field") == "KIND":
            operator, value = condition.get("operator"), condition.get("value")
            values = [value] if isinstance(value, str) else list(value or [])
            values = [entry for entry in values if entry != SAMENESS]
            if not values:
                continue
            condition = {**condition, "operator": "IS" if len(values) == 1 and operator == "IS" else operator, "value": values[0] if operator == "IS" else values}
        when.append(condition)
    return {**rule, "when": when} if when else None


def strip_sameness_from_definitions(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    for category in Category.objects.exclude(definition={}).exclude(definition__isnull=True).iterator():
        stored = category.definition
        if not isinstance(stored, dict) or not isinstance(stored.get("rules"), list):
            continue
        rules = [rule for rule in (_strip_sameness(rule) for rule in stored["rules"] if isinstance(rule, dict)) if rule]
        if rules != stored["rules"]:
            logger.info("category #%s: sameness carve-outs removed from its definition (RFC 0024)", category.pk)
            category.definition = {**stored, "rules": rules} if rules else {}
            category.save(update_fields=["definition"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0023_one_category_per_word_per_view"),
    ]

    operations = [
        migrations.AddField(
            model_name="graph",
            name="sameness_rule",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Whose SAME_AS / DIFFERENT_FROM claims this view counts — a rule list in the shape of a category definition minus WORD, KIND and KEY (RFC 0024). Empty means everyone. Identity is a property of the view, not of a category: within one view there is exactly one answer to how many things are here, and two nodes the view admits are one individual when a trusted claim says so, whatever categories each is drawn under.",
            ),
        ),
        migrations.AddField(
            model_name="historicalgraph",
            name="sameness_rule",
            field=models.JSONField(blank=True, default=dict, help_text="Whose SAME_AS / DIFFERENT_FROM claims this view counts — a rule list in the shape of a category definition minus WORD, KIND and KEY (RFC 0024). Empty means everyone. Identity is a property of the view, not of a category: within one view there is exactly one answer to how many things are here, and two nodes the view admits are one individual when a trusted claim says so, whatever categories each is drawn under."),
        ),
        migrations.RunPython(strip_sameness_from_definitions, migrations.RunPython.noop),
    ]
