"""Rebuild a graph's Apache AGE projection from the evidence base.

The operational form of the architecture's central claim. If this command cannot
reproduce a graph, the evidence is not the source of truth and the projection is
holding state nobody can account for.

Routine rather than exceptional: the projection is a cache, so dropping and
replaying it is the expected way to recover from a bad deploy, a schema change,
or a projector bug.
"""

from django.core.management.base import BaseCommand, CommandError

from api.extensions.cypher import cypher_engine
from core import models
from core.management.commands import _graphs
from graph_engine.controller import GraphController
from graph_engine.engine.age_engine import AgeEngine


class Command(BaseCommand):
    """Drop and replay one graph, or every graph."""

    help = "Rebuild a graph's AGE projection from the relational evidence base."

    def add_arguments(self, parser) -> None:
        """Declare the command's arguments."""
        parser.add_argument("--graph", help="Id or name of the graph to rebuild. Omit with --all.")
        parser.add_argument("--all", action="store_true", help="Rebuild every graph.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be rebuilt without touching the projection.",
        )

    def handle(self, *args, **options) -> None:
        """Rebuild the selected graphs."""
        if not options["graph"] and not options["all"]:
            raise CommandError("Name a graph with --graph, or pass --all.")

        graphs = self._select_graphs(options)
        if not graphs:
            raise CommandError("No matching graphs.")

        engine = self._engine()
        controller = GraphController(engine=engine)

        for graph in graphs:
            if options["dry_run"]:
                self.stdout.write(f"would rebuild {_graphs.describe(graph)}")
                continue

            self.stdout.write(f"rebuilding {_graphs.describe(graph)}…")
            result = controller.rebuild_projection(graph)
            self.stdout.write(self.style.SUCCESS(f"  {result['nodes']} nodes, {result['states']} metrics refolded, {result['projected']} entities projected"))

    def _select_graphs(self, options) -> list[models.Graph]:
        if options["all"]:
            return list(models.Graph.objects.all())
        return [_graphs.select_graph(str(options["graph"]))]

    def _engine(self) -> AgeEngine:
        """The engine bound to this process.

        Outside a GraphQL request there is no `CypherEngineExtension` to bind one
        through the ContextVar. Note the ContextVar defaults to ``None`` rather
        than raising `LookupError`, so the fallback has to test the value — not
        just catch.
        """
        try:
            engine = cypher_engine.get()
        except LookupError:
            engine = None

        if engine is not None:
            return engine

        engine = AgeEngine()
        engine.init_db()
        return engine
