"""Rebuild a graph's Apache AGE projection from the evidence base.

The operational form of the architecture's central claim. If this command cannot
reproduce a graph, the evidence is not the source of truth and the projection is
holding state nobody can account for.

Routine rather than exceptional: the projection is a cache, so dropping and
replaying it is the expected way to recover from a bad deploy, a schema change,
or a projector bug.

Two modes:

- **full** (`--graph` / `--all`): drop the namespace and replay everything the
  graph admits. The honesty test, and the only thing that moves a vertex between
  labels or brings a `NEEDS_BACKFILL` graph up.
- **incremental** (`--incremental --organization <slug>` / `--all`): apply what the
  outbox says is owed — the assertions whose synchronous projection did not
  finish — to every consistent graph of the organization, and settle exactly
  those rows. Organization-scoped because an outbox row is, and because a
  classification can widen membership in any view. `--dry-run` prints where each
  graph's cursor stands and how much work is owed. See `graph_engine/watermark.py`.
"""

from django.core.management.base import BaseCommand, CommandError

from authentikate.models import Organization

from api.extensions.cypher import cypher_engine
from core import models
from core.management.commands import _graphs
from graph_engine import watermark
from graph_engine.controller import GraphController
from graph_engine.engine.age_engine import AgeEngine


class Command(BaseCommand):
    """Drop and replay one graph, or every graph."""

    help = "Rebuild a graph's AGE projection from the relational evidence base."

    def add_arguments(self, parser) -> None:
        """Declare the command's arguments."""
        parser.add_argument("--graph", help="Id or name of the graph to rebuild. Omit with --all.")
        parser.add_argument("--all", action="store_true", help="Every graph (full), or every organization (incremental).")
        parser.add_argument("--incremental", action="store_true", help="Apply the outstanding assertions instead of dropping and replaying. Organization-scoped.")
        parser.add_argument("--organization", help="Slug of the organization to replay incrementally. Omit with --all.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be done — and, with --incremental, where every cursor stands — without touching the projection.",
        )

    def handle(self, *args, **options) -> None:
        """Rebuild the selected graphs, or replay what is owed."""
        if options["incremental"]:
            return self._incremental(options)

        if options["organization"]:
            raise CommandError("--organization goes with --incremental. A full rebuild names a graph with --graph, or --all.")
        if not options["graph"] and not options["all"]:
            raise CommandError("Name a graph with --graph, or pass --all.")

        graphs = self._select_graphs(options)
        if not graphs:
            raise CommandError("No matching graphs.")

        engine = self._engine()
        controller = GraphController(engine=engine)

        for graph in graphs:
            if options["dry_run"]:
                self.stdout.write(f"would rebuild {_graphs.describe(graph)}{self._standing(graph)}")
                continue

            self.stdout.write(f"rebuilding {_graphs.describe(graph)}…")
            result = controller.rebuild_projection(graph)
            # `states` is the organization-wide refold count, not this graph's —
            # `refold_state` is organization grain — and it is labelled as such.
            self.stdout.write(self.style.SUCCESS(f"  {result['nodes']} nodes, {result['projected']} entities projected, {result['states']} metrics refolded organization-wide; cursor at {watermark.position(graph).cursor}"))

    def _incremental(self, options) -> None:
        """Apply the outbox to every consistent graph of each selected organization."""
        if options["graph"]:
            raise CommandError("--incremental replays an organization's outstanding assertions into every graph it has; pending work is per organization, not per graph. Pass --organization <slug> or --all.")
        if not options["organization"] and not options["all"]:
            raise CommandError("Name an organization with --organization <slug>, or pass --all.")

        if options["all"]:
            organizations = list(Organization.objects.all().order_by("id"))
        else:
            organization = Organization.objects.filter(slug=options["organization"]).first()
            if organization is None:
                raise CommandError(f"No organization with slug {options['organization']!r}.")
            organizations = [organization]

        engine = self._engine()
        controller = GraphController(engine=engine)

        from graph_engine import projector

        for organization in organizations:
            graphs = list(models.Graph.objects.filter(organization=organization).order_by("id"))
            head = watermark.max_seq(organization)
            pending = watermark.pending_count(organization)
            self.stdout.write(f"{organization.slug}: log head {head}, {pending} assertion(s) outstanding")
            for graph in graphs:
                self.stdout.write(f"  {_graphs.describe(graph)}{self._standing(graph)}")

            if options["dry_run"]:
                if pending:
                    lowest = watermark.min_pending_seq(organization)
                    refs, _ = projector.touched_refs(organization, [], since_seq=lowest)
                    self.stdout.write(f"  would redraw {len(refs)} ref(s) from seq {lowest} in every consistent graph")
                continue

            result = projector.replay(controller, organization)
            for entry in result["graphs"]:
                self.stdout.write(self.style.SUCCESS(f"  {_graphs.describe(entry['graph'])}: {entry['nodes']} node(s) redrawn, {entry['erased']} erased, {entry['edges']} edge(s), {entry['participations']} participation(s), {entry['projected']} projected; cursor at {watermark.position(entry['graph']).cursor}"))
            for entry in result["skipped"]:
                self.stdout.write(self.style.WARNING(f"  {_graphs.describe(entry['graph'])}: skipped, {entry['status']} — run a full `reproject --graph {entry['graph'].pk}`"))
            self.stdout.write(self.style.SUCCESS(f"  {result['settled']} assertion(s) settled over {result['refs']} ref(s)"))

    def _standing(self, graph: models.Graph) -> str:
        position = watermark.position(graph)
        stale = ", schema stale" if position.schema_stale else ""
        return f" — {position.status}, cursor {position.cursor}/{position.max_seq}, lag {position.lag}{stale}"

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
