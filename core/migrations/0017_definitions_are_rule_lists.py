"""Definitions are rule lists (RFC 0010) — clear what the clause shape stored.

The stored shape of `Category.definition` changed from RFC 0007's clauses
(flat / `any_of`) to explicit `(field, operator, value)` rules, and
`rule.evidence` from the `RuleEvidenceInput` dict to a condition list. This was
sanctioned as **completely breaking**: no converter, no read-side tolerance —
a stored definition not in the new shape is cleared to `{}` (the category
becomes primitive) and an old-shape `evidence` is dropped, each with a loud log
naming what went. Dev-only data; anything that mattered is re-declared through
the API in the new spelling.
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def _is_rules_shaped(definition) -> bool:
    return isinstance(definition, dict) and isinstance(definition.get("rules"), list)


def sweep(apps, schema_editor):
    Category = apps.get_model("core", "Category")

    cleared = []
    for category in Category.objects.exclude(definition={}).exclude(definition__isnull=True).iterator():
        if not _is_rules_shaped(category.definition):
            cleared.append(f"graph #{category.graph_id} category #{category.pk} ({category.key!r})")
            category.definition = {}
            category.save(update_fields=["definition"])
    if cleared:
        logger.warning("RFC 0010: cleared %d clause-shaped definition(s) to primitive — re-declare through the API: %s", len(cleared), "; ".join(cleared))

    stripped = []
    for category in Category.objects.exclude(property_definitions=[]).iterator():
        changed = False
        for prop in category.property_definitions or []:
            rule = prop.get("rule") if isinstance(prop, dict) else None
            if isinstance(rule, dict) and "evidence" in rule and not isinstance(rule["evidence"], (list, type(None))):
                rule.pop("evidence", None)
                changed = True
        if changed:
            stripped.append(f"graph #{category.graph_id} category #{category.pk} ({category.key!r})")
            category.save(update_fields=["property_definitions"])
    if stripped:
        logger.warning("RFC 0010: dropped %d old-shape rule.evidence filter(s) — re-declare as conditions: %s", len(stripped), "; ".join(stripped))

    # The vocabulary index follows the definitions; refold it for every touched
    # organization so `rebuild_asserted_terms --check` holds immediately.
    if cleared:
        from core import asserted_terms

        organization_ids = set(Category.objects.values_list("graph__organization_id", flat=True))
        RealCategory = None
        try:
            from core import models as core_models

            RealCategory = core_models.Category
        except Exception:  # pragma: no cover - migration-time import guard
            RealCategory = None
        if RealCategory is not None:
            for organization_id in organization_ids:
                for category in RealCategory.objects.filter(graph__organization_id=organization_id):
                    asserted_terms.sync_category(category)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_sweep_dead_rule_keys"),
    ]

    operations = [
        migrations.RunPython(sweep, migrations.RunPython.noop),
    ]
