"""Bring stored JSON into line with the models that now forbid unknown keys.

`graph_engine.input_models.StrictModel` sets `extra="forbid"`, so every input
model in that module now rejects a key it has no field for. That is a change to
*reads*, not only to writes: eight properties on `core.models` construct these
models from JSON columns —

- `Graph.rules_model` → `ActionRuleInput`
- `Category.defined_properties` → `PropertyDefinitionInput`
- `MeasurementCategory` / `RelationCategory` / `StructureRelationCategory`
  `source_definition_model` / `target_definition_model` → `EntityDescriptorInput`
  or `StructureDescriptorInput`

— and every one of them is on a read path. A row written under an older schema,
carrying a key the model has since dropped, went from silently ignored to raising
`ValidationError` on every read of that category.

**That is the intended behaviour and the reason for the change** — a stored
filter that no longer applies silently *widens* a match, which is exactly the
failure `0004_category_tags_die` had to sweep by hand for `tags`. This migration
generalises that sweep, so the strictness lands on a database that can satisfy
it rather than on one that cannot.

The allowed key set is taken from `model_fields` at migration time rather than
hardcoded, so this file states the rule ("keys the model does not have") rather
than a snapshot of it. That means it is **not** a rerunnable guarantee for
future removals: drop a field later and its stored keys need their own sweep.
`StrictModel`'s docstring carries that warning.

Every dropped key is printed with the row it came from. A filter that stops being
applied changes what a category matches, and the only moment an operator can see
that and correct the descriptor by hand is while this runs.

Irreversible. The reverse would have to know what it removed and why the model
stopped wanting it.
"""

from django.db import migrations


def _allowed(model) -> set:
    """The keys a model will accept."""
    return set(model.model_fields.keys())


def _plain(mapping: dict) -> dict:
    """Enum members back to the strings a JSON column should hold."""
    return {key: getattr(value, "value", value) for key, value in mapping.items()}


#: Keys whose *spelling* changed rather than their meaning. These must be renamed
#: before the sweep, never stripped by it: `_allowed` reads `model_fields` from
#: the code as it stands now, so the moment a field is renamed the old spelling
#: starts looking "unknown" — and stripping it would delete a live filter rather
#: than correct it. `0006_ontology_terms_spelling` performs the same rename for
#: databases that ran this migration before the correction landed.
RENAMED_DESCRIPTOR_KEYS = {"ontotology_terms": "ontology_terms"}


def _rename(value, renames):
    """Apply spelling corrections to one stored object, in place."""
    if not isinstance(value, dict):
        return
    for old, new in renames.items():
        if old in value:
            value.setdefault(new, value.pop(old))


def _strip(value, allowed, label, dropped):
    """Drop unknown keys from one JSON object, recording what went."""
    if not isinstance(value, dict):
        return value, False
    unknown = [key for key in value if key not in allowed]
    for key in unknown:
        value.pop(key)
        dropped.append(f"{label}.{key}")
    return value, bool(unknown)


def sweep_unknown_keys(apps, schema_editor):
    """Remove keys no input model has a field for."""
    from graph_engine.input_models import (
        EntityDescriptorInput,
        PropertyDefinitionInput,
        StructureDescriptorInput,
    )

    Graph = apps.get_model("core", "Graph")
    Category = apps.get_model("core", "Category")
    dropped = []

    # `ActionRuleInput` no longer exists (`Graph.rules` was removed, RFC 0013);
    # its field set at the time this migration was written is frozen here so
    # the sweep stays replayable.
    rule_keys = {"action", "allow", "filter"}
    for graph in Graph.objects.iterator():
        rules = graph.rules or []
        changed = False
        for index, rule in enumerate(rules):
            _, hit = _strip(rule, rule_keys, f"graph:{graph.pk}.rules[{index}]", dropped)
            changed = changed or hit
        if changed:
            graph.rules = rules
            graph.save(update_fields=["rules"])

    property_keys = _allowed(PropertyDefinitionInput)
    # `type` is not a field, but it is not unknown either: it is the legacy
    # spelling of `value_kind`, and `populate_value_kind_from_legacy_type`
    # translates it. Stripping it as "unknown" would delete the only record of a
    # stored property's value kind, which is required and has no default — the
    # row would go from readable to permanently invalid. So the model's own
    # normalizer runs first and the sweep only sees what it leaves behind.
    normalize_property = PropertyDefinitionInput.populate_value_kind_from_legacy_type
    # Which descriptor model a definition is read through depends on the
    # category's kind, and the two differ (`identifiers` versus
    # `ontology_terms`). Taking the union would leave a key that the stricter of
    # the two still refuses, so each kind is swept against its own model.
    descriptor_keys = {
        "MEASUREMENT": (_allowed(StructureDescriptorInput), _allowed(EntityDescriptorInput)),
        "RELATION": (_allowed(EntityDescriptorInput), _allowed(EntityDescriptorInput)),
        "STRUCTURE_RELATION": (_allowed(StructureDescriptorInput), _allowed(StructureDescriptorInput)),
    }

    for category in Category.objects.iterator():
        label = f"category:{category.pk}"
        changed_fields = []

        definitions = category.property_definitions or []
        # `.value` because the normalizer hands back a `ValueKind` member, and
        # what goes into a JSON column should be the string it stands for rather
        # than whatever an encoder decides an enum is.
        normalized = [_plain(normalize_property(definition)) if isinstance(definition, dict) else definition for definition in definitions]
        swept = [_strip(definition, property_keys, f"{label}.property_definitions[{index}]", dropped)[0] for index, definition in enumerate(normalized)]
        if swept != definitions:
            category.property_definitions = swept
            changed_fields.append("property_definitions")

        source_keys, target_keys = descriptor_keys.get(category.kind, (None, None))
        if source_keys is not None:
            for field, allowed in (("source_definition", source_keys), ("target_definition", target_keys)):
                definition = getattr(category, field)
                before = definition.copy() if isinstance(definition, dict) else definition
                # Corrections first, so a renamed field is not mistaken for an
                # unknown one and deleted.
                _rename(definition, RENAMED_DESCRIPTOR_KEYS)
                _, hit = _strip(definition, allowed, f"{label}.{field}", dropped)
                if hit or definition != before:
                    changed_fields.append(field)

        if changed_fields:
            category.save(update_fields=changed_fields)

    if dropped:
        print(f"\n  Dropped {len(dropped)} stored key(s) no input model accepts. Where these were filters, the row now matches more broadly:")
        for entry in dropped:
            print(f"    {entry}")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_category_tags_die"),
    ]

    operations = [
        migrations.RunPython(sweep_unknown_keys, migrations.RunPython.noop),
    ]
