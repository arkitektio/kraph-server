"""Redraw the vertices of categories whose rules have moved on without them.

The out-of-band half of `api.mutations.schema._rematerialize`. The mutation
redraws inline, which is fine while a schema is being designed and wrong once a
category draws a hundred thousand entities; this command is what finishes the job
then.

It is also the repair for a redraw that never happened: a mutation that timed
out, a category edited straight through the admin or a shell, or an upgrade that
changed what `derive_properties` computes. Nothing is lost in any of those cases
— the evidence is untouched and the projection is a cache — but the graph
answers with stale numbers until something redraws it.

**Full write-up, including how `--stale` detects that work is owed and when to
reach for `reproject` instead:
[`docs/REMATERIALIZATION.md`](../../../docs/REMATERIALIZATION.md).** Two things
that decide how this file reads:

- `--stale` is the usual invocation. It costs nothing when nothing is owed,
  because `projector.project` stamps `__schema_version` on every vertex and a
  vertex behind `GraphSchema.active_for(graph)` is exactly what needs redrawing.
- **Narrower than `reproject` is not cheaper at every scale.**
  `rematerialize_category` resolves graph membership once per category, so
  `--all` over G graphs with C node categories each pays G×C full membership
  resolutions where `reproject`'s per-graph `rebuild` pays G. Naming a `--graph`
  and a `--category` is where this command wins; a whole-estate sweep is not.
"""

from django.core.management.base import BaseCommand, CommandError

from core.management.commands import _graphs

from api.extensions.cypher import cypher_engine
from core import models
from graph_engine import watermark
from graph_engine.controller import GraphController
from graph_engine.engine.age_engine import AgeEngine


class Command(BaseCommand):
    """Rewrite derived properties for the categories that need it."""

    help = "Redraw the vertices of node categories whose derivation rules have changed."

    def add_arguments(self, parser) -> None:
        """Declare the command's arguments."""
        parser.add_argument("--graph", help="Name or id of the graph to work on. Omit with --all.")
        parser.add_argument("--all", action="store_true", help="Work on every graph.")
        parser.add_argument("--category", help="Redraw only this category key, within the selected graphs.")
        parser.add_argument(
            "--stale",
            action="store_true",
            help="Only graphs whose projection was last fully derived under a schema that is no longer the active one.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be redrawn without touching the projection.",
        )

    def handle(self, *args, **options) -> None:
        """Redraw the selected categories."""
        if not options["graph"] and not options["all"]:
            raise CommandError("Name a graph with --graph, or pass --all.")

        graphs = self._select_graphs(options)
        if not graphs:
            raise CommandError("No matching graphs.")

        engine = self._engine()
        controller = GraphController(engine=engine)

        for graph in graphs:
            for category in self._select_categories(graph, options):
                if options["stale"] and not self._is_stale(controller, graph, category):
                    continue

                if options["dry_run"]:
                    self.stdout.write(f"would redraw {_graphs.describe(graph)}.{category.key}")
                    continue

                self.stdout.write(f"redrawing {_graphs.describe(graph)}.{category.key}…")
                # No `retired_keys`: nothing versions the previous definition, so
                # out of band there is no way to know which keys a *former*
                # property owned. What the category owns now is swept and
                # rewritten, which repairs a stale value but cannot reach an
                # orphan from a property that is already gone. Only the mutation,
                # which snapshots before the write, can do that — and `reproject`
                # is the fallback that can, by dropping the namespace entirely.
                projected = controller.rematerialize_category(category)
                self.stdout.write(self.style.SUCCESS(f"  {projected} vertices redrawn"))

            # Every node category of the graph has now been redrawn under the
            # active schema — or was already current — so the graph as a whole is.
            # Recorded here, at the graph level, and not inside
            # `rematerialize_category`: one category redrawn out of several is not
            # a graph that is current, and `--category` deliberately leaves the
            # ledger alone for that reason.
            if not options["dry_run"] and not options["category"]:
                watermark.record_schema_hash(graph, watermark.active_schema_hash(graph))

    def _select_graphs(self, options) -> list[models.Graph]:
        if options["all"]:
            return list(models.Graph.objects.all())
        return [_graphs.select_graph(str(options["graph"]))]

    def _select_categories(self, graph: models.Graph, options) -> list[models.Category]:
        """The node categories of one graph.

        Node categories only. An edge carries `category_id` and
        `__assertion_count` and nothing derived, so there is no such thing as a
        stale relation edge — see `update_relation_category`.
        """
        categories: list[models.Category] = []
        for manager in (
            models.EntityCategory.objects,
            models.NaturalEventCategory.objects,
            models.ProtocolEventCategory.objects,
        ):
            queryset = manager.filter(graph=graph)
            if options["category"]:
                queryset = queryset.filter(key=options["category"])
            categories.extend(queryset.order_by("key"))
        return categories

    def _is_stale(self, controller: GraphController, graph: models.Graph, category: models.Category) -> bool:
        """Was this graph's drawing last fully derived under a schema that is no longer active?

        Answered from Postgres — `Projection.schema_hash` against
        `GraphSchema.active_for(graph).hash` — not by counting vertex stamps in
        Cypher. The stamp still exists on every vertex, but the ledger of "which
        schema is this drawing at" cannot live only inside the cache it audits:
        the `reproject` that fixes a stale drawing destroys the stamps. A graph
        with no active schema is never stale: there is no version to be behind.
        Per graph, so every node category of a stale graph is redrawn.
        """
        return watermark.schema_stale(graph)

    def _engine(self) -> AgeEngine:
        """The engine bound to this process — see `reproject`, same reasoning."""
        try:
            engine = cypher_engine.get()
        except LookupError:
            engine = None

        if engine is not None:
            return engine

        engine = AgeEngine()
        engine.init_db()
        return engine
