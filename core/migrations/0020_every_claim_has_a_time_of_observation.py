"""Every claim has a time of observation (RFC 0015) — rename the rule field.

`MEASURED_AT` was the one world-time field, and only a metric row could answer
it. World time is `observed_at` on every claim now, and the field is spelled
`OBSERVED_AT` wherever a rule names it: in a category's `definition` and in
each property's `rule.evidence`. The selector returns *no predicate* for a
field it does not know, so an unrewritten condition would not fail — it would
be silently dropped, and a property that folded only last week's measurements
would fold all of them. Hence the walk, mirroring `0019`.
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)

OLD = "MEASURED_AT"
NEW = "OBSERVED_AT"


def rename_field(rule_list):
    """Rewrite the field in place in one rule-list value; True when anything changed.

    Walks `{"rules": [{"when": [...], "unless": [{"when": [...]}, ...]}, ...]}`.
    Anything not in that shape is left untouched. Exposed so the migration test
    can apply it directly.
    """
    if not isinstance(rule_list, dict):
        return False
    changed = False
    for rule in rule_list.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        groups = [rule] + [group for group in (rule.get("unless") or []) if isinstance(group, dict)]
        for group in groups:
            for condition in group.get("when") or []:
                if isinstance(condition, dict) and condition.get("field") == OLD:
                    condition["field"] = NEW
                    changed = True
    return changed


def rename(apps, schema_editor):
    Category = apps.get_model("core", "Category")

    converted = []
    for category in Category.objects.iterator():
        changed = rename_field(category.definition)
        for prop in category.property_definitions or []:
            rule = prop.get("rule") if isinstance(prop, dict) else None
            if isinstance(rule, dict) and rename_field(rule.get("evidence")):
                changed = True
        if changed:
            converted.append(f"graph #{category.graph_id} category #{category.pk} ({category.key!r})")
            category.save(update_fields=["definition", "property_definitions"])
    if converted:
        logger.info("RFC 0015: renamed %s to %s in %d category definition(s): %s", OLD, NEW, len(converted), "; ".join(converted))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_property_evidence_is_a_rule_list"),
    ]

    operations = [
        migrations.RunPython(rename, migrations.RunPython.noop),
    ]
