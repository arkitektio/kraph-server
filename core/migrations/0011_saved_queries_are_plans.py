"""The saved-query contract is a plan, and only the table kind exists.

- `GraphQuery.plan` (JSON, `graph_engine.query_ir.TableQueryPlan`) replaces the
  three builder columns `matches` / `wheres` / `returns`. Rows the builder wrote
  are folded into a plan; rows that stored only raw Cypher keep it in `query`
  (now nullable, read-only) and are **legacy** — `manage.py list_legacy_queries`
  names them so they can be rebuilt through the builder.
- `NodeQuery`, `EdgeQuery`, their proxies, and the `NODES` / `PATH` / `PAIRS`
  kinds of `GraphQuery` are removed. They had mutations, types and filters but
  **no execution path anywhere** — nothing could ever render one — so the rows
  they left are definitions that never did anything. They are deleted here
  rather than orphaned under an enum that no longer names them. `ScatterPlot`
  loses `node_query` / `path_query` for the same reason and requires
  `graph_query`; a plot over nothing is deleted too.
"""

import django.db.models.deletion
from django.db import migrations, models


def fold_plans_and_drop_the_unrenderable(apps, schema_editor):
    GraphQuery = apps.get_model("core", "GraphQuery")
    ScatterPlot = apps.get_model("core", "ScatterPlot")

    ScatterPlot._default_manager.filter(graph_query__isnull=True).delete()
    GraphQuery._default_manager.exclude(kind="TABLE").delete()

    for row in GraphQuery._default_manager.filter(kind="TABLE"):
        matches = row.matches or []
        if not matches:
            continue  # a raw-Cypher row: legacy, renders through `query`
        row.plan = {
            "version": 1,
            "matches": matches,
            "wheres": row.wheres or [],
            "returns": row.returns or [],
            "columns": row.columns or [],
        }
        row.save(update_fields=["plan"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_graph_age_name_is_a_handle"),
    ]

    operations = [
        migrations.AddField(
            model_name="graphquery",
            name="plan",
            field=models.JSONField(blank=True, help_text="The saved query as a `TableQueryPlan` (matches, wheres, returns, columns). Null only on a legacy row that stores raw Cypher.", null=True),
        ),
        migrations.RunPython(fold_plans_and_drop_the_unrenderable, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(name="edgequery", unique_together=None),
        migrations.RemoveField(model_name="edgequery", name="graph"),
        migrations.RemoveField(model_name="edgequery", name="pinned_by"),
        migrations.RemoveField(model_name="edgequery", name="relevant_for_edges"),
        migrations.AlterUniqueTogether(name="nodequery", unique_together=None),
        migrations.RemoveField(model_name="nodequery", name="graph"),
        migrations.RemoveField(model_name="nodequery", name="pinned_by"),
        migrations.RemoveField(model_name="nodequery", name="relevant_for_nodes"),
        migrations.RemoveField(model_name="scatterplot", name="node_query"),
        migrations.RemoveField(model_name="scatterplot", name="path_query"),
        migrations.DeleteModel(name="EdgePairsQuery"),
        migrations.DeleteModel(name="EdgePathQuery"),
        migrations.DeleteModel(name="EdgeTableQuery"),
        migrations.DeleteModel(name="GraphNodesQuery"),
        migrations.DeleteModel(name="GraphPairsQuery"),
        migrations.DeleteModel(name="GraphPathQuery"),
        migrations.DeleteModel(name="NodePairsQuery"),
        migrations.DeleteModel(name="NodePathQuery"),
        migrations.DeleteModel(name="NodeTableQuery"),
        migrations.RemoveField(model_name="graphquery", name="left_category"),
        migrations.RemoveField(model_name="graphquery", name="matches"),
        migrations.RemoveField(model_name="graphquery", name="node_category"),
        migrations.RemoveField(model_name="graphquery", name="returns"),
        migrations.RemoveField(model_name="graphquery", name="right_category"),
        migrations.RemoveField(model_name="graphquery", name="wheres"),
        migrations.AlterField(
            model_name="graphquery",
            name="columns",
            field=models.JSONField(default=list, help_text="How the returned aliases are presented. Mirrors `plan.columns` for rows that have a plan", null=True),
        ),
        migrations.AlterField(
            model_name="graphquery",
            name="kind",
            field=models.CharField(choices=[("TABLE", "Table")], help_text="The kind of result this query renders. Only TABLE exists.", max_length=1000),
        ),
        migrations.AlterField(
            model_name="graphquery",
            name="query",
            field=models.CharField(blank=True, help_text="Legacy: raw Cypher saved before plans existed. Read-only; never accepted any more.", max_length=7000, null=True),
        ),
        migrations.AlterField(
            model_name="scatterplot",
            name="graph_query",
            field=models.ForeignKey(help_text="The graph table query this scatter plot is drawn from", on_delete=django.db.models.deletion.CASCADE, related_name="scatter_plots", to="core.graphtablequery"),
        ),
        migrations.DeleteModel(name="EdgeQuery"),
        migrations.DeleteModel(name="NodeQuery"),
    ]
