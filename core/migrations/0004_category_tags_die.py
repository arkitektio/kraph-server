"""Category tags are gone — the table, the many-to-many, and the stored filters.

A `CategoryTag` was a free-text label scoped to one graph, attached to categories
by an M2M, and read back in exactly one place: `tags__value__in` inside
`RelationCategory.get_matching_*_entities` and
`MeasurementCategory.get_matching_target_entities`, which expand a relation
category into `MaterializedRelationEdge` rows. Nothing else consulted it. It was a
second, weaker naming system sitting beside the two that carry meaning — the
category's `key`, and the organization-scoped `Term` the evidence log actually
names — with no term to join on, so a tag could not be read across views and
could not appear in a claim.

**The JSON has to be swept too, and that is what makes this more than a
`DeleteModel`.** A `RelationCategory`'s source and target descriptors are stored
as JSON on `Category.source_definition` / `target_definition`, and one may carry
`{"tags": [...]}` written before this change. `EntityDescriptorInput` has no
`tags` field any more, so such a row keeps an instruction nothing applies, and
the match it once narrowed *widens*: the category expands into materialized edges
between pairs its author had excluded.

The widening is unavoidable once the filter has nothing to filter on — doing it
silently is the part that is not. So it happens **here, once, out loud**: the
affected categories are printed as this migration runs, which is the only moment
an operator can see the change and correct the descriptors by hand.

`0005_strict_input_models` generalises this sweep to every key no input model has
a field for, and turns a missed one into a hard error rather than a silent widen.
This migration stays as it is: it must run first, since it is what deletes the
column and the table that made `tags` a key in the first place.

Stripped, not migrated onto `keys`: a tag and a key are different words. Turning
`tags: ["excitatory"]` into `keys: ["excitatory"]` would invent a category
membership nobody declared. Widening the match is the honest loss, and it is
recorded here so it can be found later; the affected rows are printed as the
migration runs.

Irreversible. The reverse would have to reconstruct labels from nothing.
"""

from django.db import migrations


def strip_tags_from_descriptors(apps, schema_editor):
    """Drop the `tags` key from every stored edge descriptor."""
    Category = apps.get_model("core", "Category")
    touched = []

    for category in Category.objects.iterator():
        changed = False
        for field in ("source_definition", "target_definition"):
            definition = getattr(category, field)
            if isinstance(definition, dict) and definition.get("tags"):
                definition.pop("tags")
                changed = True
        if changed:
            category.save(update_fields=["source_definition", "target_definition"])
            touched.append(f"{category.graph_id}:{category.key}")

    if touched:
        print(f"\n  Dropped tag filters from {len(touched)} edge descriptor(s); these categories now match more broadly: {', '.join(touched)}")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_archiving_is_real"),
    ]

    operations = [
        migrations.RunPython(strip_tags_from_descriptors, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="category",
            name="tags",
        ),
        migrations.DeleteModel(
            name="CategoryTag",
        ),
    ]
