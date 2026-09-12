"""Rebuild graphs' queryable namespaces from their categories.

The namespace — one Postgres schema per graph holding the per-category views and
the SQL/PGQ property graph — is derived DDL (RFC 0006): every category write
refreshes it in the same transaction, so under normal operation it is never
stale. This command is the out-of-band repair, the same role
`rebuild_asserted_terms` plays for its cache: after a restore, after DDL was
dropped by hand, or after upgrading past a change in the generated shape
(a Postgres GA that moves SQL/PGQ syntax, say — the namespace is regenerable,
so that is a run of this command, not a data migration).
"""

from django.core.management.base import BaseCommand, CommandError

from authentikate.models import Organization

from core import models
from core.management.commands import _graphs
from graph_engine.projection.context import current_or_default


class Command(BaseCommand):
    """Re-derive the namespace DDL for one graph, an organization, or all."""

    help = "Rebuild graphs' per-graph schemas and property graphs from their categories."

    def add_arguments(self, parser) -> None:
        """Declare the command's arguments."""
        parser.add_argument("--graph", help="Id or name of the graph to refresh. Omit with --all or --organization.")
        parser.add_argument("--organization", help="Slug of the organization whose graphs to refresh.")
        parser.add_argument("--all", action="store_true", help="Every graph.")

    def handle(self, *args, **options) -> None:
        """Refresh the selected graphs' namespaces."""
        chosen = [bool(options["graph"]), bool(options["organization"]), bool(options["all"])]
        if sum(chosen) != 1:
            raise CommandError("Pass exactly one of --graph, --organization or --all.")

        if options["graph"]:
            graphs = [_graphs.select_graph(options["graph"])]
        elif options["organization"]:
            organization = Organization.objects.filter(slug=options["organization"]).first()
            if organization is None:
                raise CommandError(f"No organization is slugged {options['organization']!r}.")
            graphs = list(models.Graph.objects.filter(organization=organization).order_by("id"))
        else:
            graphs = list(models.Graph.objects.order_by("id"))

        projector = current_or_default()
        for graph in graphs:
            projector.refresh_namespace(graph)
            self.stdout.write(f"refreshed namespace of {_graphs.describe(graph)}")
        self.stdout.write(self.style.SUCCESS(f"{len(graphs)} namespace(s) refreshed."))
