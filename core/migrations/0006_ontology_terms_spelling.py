"""Correct the stored spelling of `ontotology_terms`.

The field was `ontotology_terms` — with an extra `to` — on
`EntityDescriptorInput` and `StructureDescriptorInput`, which put
`ontotologyTerms` in the GraphQL schema and `"ontotology_terms"` into every
stored descriptor. It is `ontology_terms` now.

**This sweep is mandatory, not cosmetic.** `Category.source_definition` and
`target_definition` are JSON columns read back through those pydantic models
(`core/models.py`, the `*_definition_model` properties), and since
`0005_strict_input_models` those models set `extra="forbid"`. So a row still
carrying the old key does not quietly ignore it — it raises `ValidationError` on
every read of that category, which means every read of the relation or
measurement category it belongs to.

Renaming rather than dropping: unlike the `tags` sweep in
`0004_category_tags_die`, nothing about the *meaning* changed here. The filter
still selects the same ontology references; only its name was wrong. So the value
moves across and the match a descriptor expresses is unaffected.

**Ordering matters, and `0005` was corrected for it.** That migration strips keys
no input model has a field for, and it reads the field list from the code as it
stands — so once the spelling was corrected, `ontotology_terms` started looking
"unknown" to it and would have been *deleted* rather than renamed, taking a live
filter with it. `0005` now renames before it strips. This migration exists for
databases that ran `0005` before that correction landed; on any database migrated
after it, it finds nothing and says nothing.

The reverse is exact, which is why this one is reversible where the other two
were not: the same rename in the other direction restores the previous state
byte for byte.
"""

from django.db import migrations

OLD_KEY = "ontotology_terms"
NEW_KEY = "ontology_terms"


def _rename(definition, old, new) -> bool:
    """Move `old` to `new` in one stored descriptor. True if anything moved."""
    if not isinstance(definition, dict) or old not in definition:
        return False
    value = definition.pop(old)
    # If the corrected key is somehow already there, the corrected one wins: it
    # is the one the model will read, so preferring it keeps the row's behaviour
    # unchanged rather than silently swapping the filter.
    definition.setdefault(new, value)
    return True


def _sweep(apps, old, new):
    Category = apps.get_model("core", "Category")
    touched = []

    for category in Category.objects.iterator():
        changed = []
        for field in ("source_definition", "target_definition"):
            if _rename(getattr(category, field), old, new):
                changed.append(field)
        if changed:
            category.save(update_fields=changed)
            touched.append(f"{category.graph_id}:{category.key}")

    if touched:
        print(f"\n  Renamed {old!r} to {new!r} in {len(touched)} descriptor(s): {', '.join(touched)}")


def forwards(apps, schema_editor):
    _sweep(apps, OLD_KEY, NEW_KEY)


def backwards(apps, schema_editor):
    _sweep(apps, NEW_KEY, OLD_KEY)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_strict_input_models"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
