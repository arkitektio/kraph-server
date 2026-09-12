"""Sweep the two dead knobs out of stored JSON (RFC 0009).

`DerivationRuleInput.conflict_policy` and `ActionRuleInput.filter` are gone from
the input models, and `StrictModel` (`extra="forbid"`) means a stored row still
carrying them would fail to parse on read-back — `defined_properties` for the
rule, `Graph.rules_model` for the action rule. Every stored rule carries
`"conflict_policy": "COMBINE"` (written by `model_dump(mode="json")`) and every
stored action rule a `"filter"`, so this is a full-table rewrite, mirroring
`0005_strict_input_models`: sweep, no read-side tolerance.

Historic `GraphSchema.definition` snapshots are raw JSON re-parsed only through
`Graph.definition`; they are swept too, for the same reason.
"""

from django.db import migrations


def _clean_property_definitions(property_definitions):
    changed = False
    for prop in property_definitions or []:
        rule = prop.get("rule") if isinstance(prop, dict) else None
        if isinstance(rule, dict) and "conflict_policy" in rule:
            rule.pop("conflict_policy", None)
            changed = True
    return changed


def _clean_rules(rules):
    changed = False
    for rule in rules or []:
        if isinstance(rule, dict) and "filter" in rule:
            rule.pop("filter", None)
            changed = True
    return changed


def _clean_definition_blob(definition):
    changed = False
    if not isinstance(definition, dict):
        return False
    if _clean_rules(definition.get("rules")):
        changed = True
    extensions = definition.get("extensions") or {}
    for family in ("entities", "events", "relations", "structure_relations", "measurements"):
        for entry in extensions.get(family) or []:
            if not isinstance(entry, dict):
                continue
            for key in ("property_definitions", "properties"):
                if _clean_property_definitions(entry.get(key)):
                    changed = True
    return changed


def sweep(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    for category in Category.objects.exclude(property_definitions=[]).iterator():
        if _clean_property_definitions(category.property_definitions):
            category.save(update_fields=["property_definitions"])

    Graph = apps.get_model("core", "Graph")
    for graph in Graph.objects.exclude(rules=[]).iterator():
        if _clean_rules(graph.rules):
            graph.save(update_fields=["rules"])

    GraphSchema = apps.get_model("core", "GraphSchema")
    for schema in GraphSchema.objects.iterator():
        if _clean_definition_blob(schema.definition):
            schema.save(update_fields=["definition"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_remove_graph_selector_and_more"),
    ]

    operations = [
        migrations.RunPython(sweep, migrations.RunPython.noop),
    ]
