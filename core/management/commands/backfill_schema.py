"""Apply a schema change to the data it actually affects.

The expand-contract half of schema versioning. Under the old design every schema
edit implied recalculating everything, because there was no way to tell what had
changed. With versions to diff, the work set is usually small and frequently
empty — an aggregation swap needs no backfill at all, because the state vector
holds statistics rather than an answer.

Restartable and idempotent: it recomputes from evidence, so running it twice
produces the same result, and it can be interrupted without leaving the
projection in a state that needs manual repair.
"""

from django.core.management.base import BaseCommand, CommandError

from api.extensions.cypher import cypher_engine
from core import models
from graph_engine import schema_diff
from graph_engine.controller import GraphController
from graph_engine.engine.age_engine import AgeEngine


class Command(BaseCommand):
    """Re-derive the entities a schema change affects, and only those."""

    help = "Backfill derived values for the categories a schema change touched."

    def add_arguments(self, parser) -> None:
        """Declare the command's arguments."""
        parser.add_argument("--graph", required=True, help="Name or id of the graph.")
        parser.add_argument(
            "--from-version",
            type=int,
            help="Schema index to diff from. Defaults to the version before the active one.",
        )
        parser.add_argument("--to-version", type=int, help="Schema index to diff to. Defaults to the active one.")
        parser.add_argument("--dry-run", action="store_true", help="Report the work set without doing it.")

    def handle(self, *args, **options) -> None:
        """Diff two schema versions and re-derive what changed."""
        graph = self._graph(options["graph"])
        before, after = self._versions(graph, options)

        difference = schema_diff.diff_schemas(before, after)

        self.stdout.write(f"{graph.name}: v{before.index} -> v{after.index}")
        for change in difference.changes:
            marker = "work" if change.needs_reprojection else "free"
            self.stdout.write(f"  [{marker}] {change.category_key}.{change.property_key}: {change.kind}")

        if difference.is_free:
            self.stdout.write(self.style.SUCCESS("  nothing to backfill — the change is answerable from the statistics already held"))
            return

        if options["dry_run"]:
            self.stdout.write(f"  would re-derive: {sorted(difference.categories_needing_reprojection)}")
            return

        projected = self._reproject(graph, difference.categories_needing_reprojection)
        self.stdout.write(self.style.SUCCESS(f"  re-derived {projected} entities"))

    def _graph(self, identifier: str) -> models.Graph:
        found = models.Graph.objects.filter(name=identifier) | models.Graph.objects.filter(age_name=identifier)
        if str(identifier).isdigit():
            found = models.Graph.objects.filter(id=int(identifier))
        graph = found.first()
        if graph is None:
            raise CommandError(f"No graph matching {identifier!r}.")
        return graph

    def _versions(self, graph: models.Graph, options) -> tuple[models.GraphSchema, models.GraphSchema]:
        schemas = models.GraphSchema.objects.filter(graph=graph).order_by("index")

        after = schemas.filter(index=options["to_version"]).first() if options["to_version"] else models.GraphSchema.active_for(graph)
        if after is None:
            raise CommandError("No target schema. Has this graph been materialized?")

        if options["from_version"]:
            before = schemas.filter(index=options["from_version"]).first()
        else:
            before = schemas.filter(index__lt=after.index).order_by("-index").first()

        if before is None:
            raise CommandError(f"No earlier schema to diff against (target is v{after.index}). A graph's first schema has nothing to backfill from.")
        return before, after

    def _reproject(self, graph: models.Graph, category_keys: set[str]) -> int:
        """Re-derive the nodes whose category's rules changed.

        Membership comes from `selector.instances_for`, the one function that decides
        it. The filter here was written against a `Instance` that no longer exists and
        could not have matched anything: it tested `ref__startswith="{age_name}:"`,
        but `ref` is a property rather than a column and refs carry no graph prefix
        any more; it filtered `stands=True`, and `Instance` deliberately has no cached
        `stands`; and it joined `category__key`, where the field is `term`.

        Standing is not filtered, deliberately. `project` writes derived properties
        onto vertices that exist, so a retracted node — which has no vertex —
        contributes nothing and needs no special case.
        """
        from evidence import selector as selector_module

        engine = self._engine()
        controller = GraphController(engine=engine)

        refs = [str(node_id) for node_id in selector_module.instances_for(graph).filter(term__key__in=list(category_keys)).values_list("id", flat=True)]
        return controller.project_entities(graph, refs)

    def _engine(self) -> AgeEngine:
        """The engine bound to this process. See `reproject` for why None is tested."""
        try:
            engine = cypher_engine.get()
        except LookupError:
            engine = None
        if engine is not None:
            return engine
        engine = AgeEngine()
        engine.init_db()
        return engine
