"""Drop the stored cross-product of the category pairs an edge category permits.

`MaterializedEdge` and its three proxies held, per graph, one row per
(source, target) category pair that a relation / measurement / structure-relation
category's `source_definition` × `target_definition` predicates admitted. It was a
read surface for a schema editor — never a write-time guard, as
`controller.create_relation` says in as many words.

It goes because it was a cache with no invalidation, and the gap was not
theoretical:

- `re_materialize_from_entity_category` — the function whose only job was
  refreshing the cross-product when a new entity category widened a predicate —
  had **no callers**, so adding a category never refreshed anything.
- `createRelationCategory` / `updateRelationCategory` never populated it at all,
  so relation pairs existed only for categories built by the bulk `materialize()`
  path. A relation category created through the API had zero rows, permanently.
- Only measurement and structure-relation categories refreshed on mutation.

The question the rows answered is still answerable, and cheaply: it is
`get_matching_source_entities()` × `get_matching_target_entities()` over the
graph's *categories*, which are schema-sized. See RFC 0001 §6.

`MaterializedView` (a query snapshot nothing ever wrote) and `Model` (a
deep-learning-model row whose only foreign key pointed at `MaterializedView`) go
with it — neither had a reader, a writer or a GraphQL type.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_asserted_terms_index'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='materializededge',
            name='edge_category',
        ),
        migrations.RemoveField(
            model_name='materializededge',
            name='graph',
        ),
        migrations.RemoveField(
            model_name='materializededge',
            name='source_category',
        ),
        migrations.RemoveField(
            model_name='materializededge',
            name='source_structure_kind',
        ),
        migrations.RemoveField(
            model_name='materializededge',
            name='target_category',
        ),
        migrations.RemoveField(
            model_name='materializededge',
            name='target_structure_kind',
        ),
        migrations.RemoveField(
            model_name='materializedview',
            name='creator',
        ),
        migrations.RemoveField(
            model_name='materializedview',
            name='query',
        ),
        migrations.RemoveField(
            model_name='model',
            name='materialized_graph',
        ),
        migrations.RemoveField(
            model_name='model',
            name='store',
        ),
        migrations.DeleteModel(
            name='MaterializedMeasurementEdge',
        ),
        migrations.DeleteModel(
            name='MaterializedRelationEdge',
        ),
        migrations.DeleteModel(
            name='MaterializedStructureRelationEdge',
        ),
        migrations.DeleteModel(
            name='MaterializedEdge',
        ),
        migrations.DeleteModel(
            name='MaterializedView',
        ),
        migrations.DeleteModel(
            name='Model',
        ),
    ]
