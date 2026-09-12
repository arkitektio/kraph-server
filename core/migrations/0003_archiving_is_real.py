"""Give the archive flags somewhere to be stored.

Eleven mutations wrote a flag that was on no model — `archive_graph` and
`update_graph`'s `archived` branch set `Graph.is_archived`, and nine
`archive_*_query` resolvers set `archived` on the saved-query tables. Python
took the attribute, `save()` persisted nothing, and the caller was told it had
worked. No GraphQL type exposed either value, so a client could write one and
never observe that it had not taken.

`archived` lands on the three concrete query tables only. The other six query
models are proxies over them, so all nine mutations are covered by three
columns.

The `Category.definition` alter is help text, unrelated and pending from an
earlier change on this branch.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='edgequery',
            name='archived',
            field=models.BooleanField(default=False, help_text='Whether this saved query has been put away. Archiving is the reversible alternative to deleting it.'),
        ),
        migrations.AddField(
            model_name='graph',
            name='is_archived',
            field=models.BooleanField(default=False, help_text="Whether this graph has been put away. Archiving is the sanctioned alternative to deleting — `delete_graph`'s own refusal points at it — because deleting a graph destroys every rule for reading the evidence while the evidence itself survives. This field did not exist until now: `archive_graph` set the attribute on the Python object and called `save()`, which persisted nothing and told the caller it had worked. Nothing read it back either, since no GraphQL type exposed it, so a client could write the value and never observe that it had not taken. It is a container flag, not evidence: it says nothing about the world, only about what this user wants to see, so it is ordinary mutable Django state and carries no assertion."),
        ),
        migrations.AddField(
            model_name='graphquery',
            name='archived',
            field=models.BooleanField(default=False, help_text='Whether this saved query has been put away. Archiving is the reversible alternative to deleting it.'),
        ),
        migrations.AddField(
            model_name='historicalgraph',
            name='is_archived',
            field=models.BooleanField(default=False, help_text="Whether this graph has been put away. Archiving is the sanctioned alternative to deleting — `delete_graph`'s own refusal points at it — because deleting a graph destroys every rule for reading the evidence while the evidence itself survives. This field did not exist until now: `archive_graph` set the attribute on the Python object and called `save()`, which persisted nothing and told the caller it had worked. Nothing read it back either, since no GraphQL type exposed it, so a client could write the value and never observe that it had not taken. It is a container flag, not evidence: it says nothing about the world, only about what this user wants to see, so it is ordinary mutable Django state and carries no assertion."),
        ),
        migrations.AddField(
            model_name='nodequery',
            name='archived',
            field=models.BooleanField(default=False, help_text='Whether this saved query has been put away. Archiving is the reversible alternative to deleting it.'),
        ),
        migrations.AlterField(
            model_name='category',
            name='definition',
            field=models.JSONField(blank=True, default=dict, help_text="What this category *means in this graph*, as a predicate over classification claims. Empty means primitive: membership is whatever was asserted, which is the default and the old behaviour. Non-empty makes it a defined category — necessary and sufficient conditions, evaluated at projection time, so 'AIS' can mean 'asserted AIS by Johannes before August' in one graph and something else in another without touching a single piece of evidence. Shape: {asserted_as: <term key or list of them>, assertion_filter: {subjects, app_ids, action_names}, as_of: timestamp}. `asserted_as` takes several words and means *any of*, so a view's 'Neuron' can be 'anything claimed Pyramidal or Interneuron' — a category derives from many words while `term` is the single one it asserts as. Naming a word this graph declares no category for is fine and is the interesting case; `evidence.selector.term_ids_for` widens membership to cover it."),
        ),
    ]
