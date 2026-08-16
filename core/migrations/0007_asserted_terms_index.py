"""Normalize the half of `Category.definition` nothing could join against.

A graph derives from a word by naming it in ``definition.asserted_as``, a string
inside JSON — so `selector._graph_ids_by_term`, which every instance write goes
through, read every category in the organization and pulled every definition blob
out of the database to parse in Python.

The backfill is not optional. `_graph_ids_by_term` reads this table from the
moment the code lands, so an empty one would mean every existing defined category
silently stops deriving from its words — nodes would vanish from the views that
define them rather than declare them, which is exactly the failure
`selector.term_ids_for` documents having already been fixed once.
"""

import django.db.models.deletion
from django.db import migrations, models


def _index_existing_definitions(apps, schema_editor):
    """Write the rows every existing definition implies.

    Reads `asserted_as` through `evidence.selector.asserted_as_keys` — a pure
    function over a dict, safe to import into a migration — rather than
    re-implementing the "a bare string means one word" rule here. Two spellings of
    it would make the backfilled rows disagree with the ones the signal writes
    afterwards.
    """
    from evidence.selector import asserted_as_keys

    Category = apps.get_model("core", "Category")
    CategoryAssertedTerm = apps.get_model("core", "CategoryAssertedTerm")

    rows = []
    for category_id, graph_id, organization_id, definition in Category.objects.values_list("id", "graph_id", "graph__organization_id", "definition"):
        if graph_id is None or organization_id is None:
            continue
        for key in dict.fromkeys(asserted_as_keys(definition)):
            rows.append(
                CategoryAssertedTerm(
                    organization_id=organization_id,
                    graph_id=graph_id,
                    category_id=category_id,
                    key=key,
                )
            )

    CategoryAssertedTerm.objects.bulk_create(rows, batch_size=1000)


def _drop_index(apps, schema_editor):
    """Reverse: the table goes with the migration, so there is nothing to undo."""
    apps.get_model("core", "CategoryAssertedTerm").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('authentikate', '0006_alter_app_identifier_alter_release_unique_together'),
        ('core', '0006_ontology_terms_spelling'),
    ]

    operations = [
        migrations.CreateModel(
            name='CategoryAssertedTerm',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(help_text='The word, exactly as `definition.asserted_as` spells it.', max_length=1000)),
                ('category', models.ForeignKey(help_text='The category whose definition names this word. Rows are rewritten wholesale when it changes, because a definition can stop naming a word as easily as start.', on_delete=django.db.models.deletion.CASCADE, related_name='asserted_terms', to='core.category')),
                ('graph', models.ForeignKey(help_text="Denormalized from the category: the read is 'which graphs derive from this word', and without it the seek becomes a join.", on_delete=django.db.models.deletion.CASCADE, related_name='asserted_terms', to='core.graph')),
                ('organization', models.ForeignKey(help_text='Denormalized from the graph, so the organization-wide map is one indexed scan rather than a join.', on_delete=django.db.models.deletion.CASCADE, related_name='category_asserted_terms', to='authentikate.organization')),
            ],
            options={
                'indexes': [models.Index(fields=['organization', 'key'], name='core_catego_organiz_c3ed77_idx'), models.Index(fields=['organization', 'graph'], name='core_catego_organiz_86d945_idx')],
                'constraints': [models.UniqueConstraint(fields=('category', 'key'), name='unique_asserted_term_per_category')],
            },
        ),
        migrations.RunPython(_index_existing_definitions, _drop_index),
    ]
