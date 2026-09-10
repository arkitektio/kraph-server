"""Rebuild a graph's projection from the evidence base, or converge what the outbox owes.

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
  `--loop` turns it into the **runner**: the same pass every `--interval`
  seconds, under the organization's projection lock, until SIGTERM. This is
  what `run-worker.sh` starts; see `graph_engine/runner.py`.
"""

import datetime
import signal
import threading

from django.core.management.base import BaseCommand, CommandError

from authentikate.models import Organization

from api.extensions.projection import current_or_default
from core import models
from core.management.commands import _graphs
from graph_engine import watermark
from graph_engine.controller import GraphController


class Command(BaseCommand):
    """Drop and replay one graph, or every graph."""

    help = "Rebuild a graph's projection from the evidence base, or apply what the outbox owes (--incremental, --loop)."

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
        parser.add_argument("--loop", action="store_true", help="With --incremental: keep applying the outbox every --interval seconds until SIGTERM. The runner.")
        parser.add_argument("--interval", type=float, default=None, help="Seconds between passes in --loop mode (default 30).")
        parser.add_argument("--grace", type=float, default=None, help="Leave outbox rows younger than this many seconds for the next pass (default 0; 30 in --loop mode) — the request that wrote them may still be drawing.")

    def handle(self, *args, **options) -> None:
        """Rebuild the selected graphs, or replay what is owed."""
        if options["incremental"]:
            return self._incremental(options)

        for flag in ("loop", "interval", "grace"):
            if options.get(flag) not in (None, False):
                raise CommandError(f"--{flag} goes with --incremental: only the outbox is applied repeatedly; a full rebuild is a deliberate, one-off act.")
        if options["organization"]:
            raise CommandError("--organization goes with --incremental. A full rebuild names a graph with --graph, or --all.")
        if not options["graph"] and not options["all"]:
            raise CommandError("Name a graph with --graph, or pass --all.")

        graphs = self._select_graphs(options)
        if not graphs:
            raise CommandError("No matching graphs.")

        controller = GraphController(projector=current_or_default())

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

        controller = GraphController(projector=current_or_default())

        from graph_engine import projector, runner

        if options["loop"]:
            if options["dry_run"]:
                raise CommandError("--loop applies the outbox; --dry-run only reports it. Pick one.")
            return self._loop(controller, options)
        if options["interval"] is not None:
            raise CommandError("--interval goes with --loop.")

        grace = datetime.timedelta(seconds=float(options["grace"])) if options["grace"] else None

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

            # Through the runner, so the manual command and the loop share one
            # policy: the organization's projection lock, waited for here.
            [done] = runner.run_once(controller, [organization], wait_for_lock=True, older_than=grace)
            if done.idle:
                self.stdout.write("  nothing owed")
                continue
            result = done.report or {"graphs": [], "skipped": [], "settled": 0, "refs": 0}
            for entry in result["graphs"]:
                self.stdout.write(self.style.SUCCESS(f"  {_graphs.describe(entry['graph'])}: {entry['nodes']} node(s) redrawn, {entry['erased']} erased, {entry['edges']} edge(s), {entry['participations']} participation(s), {entry['projected']} projected; cursor at {watermark.position(entry['graph']).cursor}"))
            for entry in result["skipped"]:
                self.stdout.write(self.style.WARNING(f"  {_graphs.describe(entry['graph'])}: skipped, {entry['status']} — run a full `reproject --graph {entry['graph'].pk}`"))
            self.stdout.write(self.style.SUCCESS(f"  {result['settled']} assertion(s) settled over {result['refs']} ref(s)"))

    def _loop(self, controller, options) -> None:
        """The runner: `run_forever` until SIGTERM/SIGINT, then exit 0 after the current pass."""
        from graph_engine import runner

        interval = float(options["interval"]) if options["interval"] is not None else 30.0
        grace = datetime.timedelta(seconds=float(options["grace"]) if options["grace"] is not None else 30.0)
        if options["organization"]:
            self.stdout.write(self.style.WARNING("--loop watches every organization; --organization is ignored in loop mode."))

        stop = threading.Event()

        def on_signal(signum, frame) -> None:
            self.stdout.write(f"received {signal.Signals(signum).name}; stopping after the current pass")
            stop.set()

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, on_signal)
            signal.signal(signal.SIGINT, on_signal)

        self.stdout.write(f"runner: applying the outbox every {interval:g}s (grace {grace.total_seconds():g}s)")
        state = runner.run_forever(controller, interval=interval, stop=stop, older_than=grace)
        self.stdout.write(f"runner stopped after {state.passes} pass(es), {state.failures} failure(s)")

    def _standing(self, graph: models.Graph) -> str:
        position = watermark.position(graph)
        stale = ", schema stale" if position.schema_stale else ""
        return f" — {position.status}, cursor {position.cursor}/{position.max_seq}, lag {position.lag}{stale}"

    def _select_graphs(self, options) -> list[models.Graph]:
        if options["all"]:
            return list(models.Graph.objects.all())
        return [_graphs.select_graph(str(options["graph"]))]

