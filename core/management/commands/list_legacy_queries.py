"""Name the saved queries that still store raw Cypher instead of a plan.

A saved table query is a plan now (`graph_engine/query_ir.py`), compiled by the
projection kind in use. Rows saved before that store the Cypher a client wrote in
`GraphQuery.query` and nothing else: they still render, but cannot be filtered,
ordered or paged, and cannot be drawn by any other projection kind. Rebuilding
one through the builder (`createGraphTableQueryThroughBuilder`, or
`updateGraphTableQuery(input: {plan: …})`) is the fix; this command says which.
"""

from django.core.management.base import BaseCommand

from core import models


class Command(BaseCommand):
    """List saved table queries with no plan."""

    help = "List saved table queries that still store raw Cypher and have no plan."

    def handle(self, *args, **options) -> None:
        legacy = list(models.GraphTableQuery.objects.filter(plan__isnull=True).select_related("graph").order_by("graph_id", "id"))
        if not legacy:
            self.stdout.write(self.style.SUCCESS("No legacy saved queries: every table query has a plan."))
            return
        self.stdout.write(f"{len(legacy)} legacy saved quer{'y' if len(legacy) == 1 else 'ies'} (raw Cypher, no plan):")
        for row in legacy:
            self.stdout.write(f"  #{row.pk} {row.key!r} in graph {row.graph.name} (#{row.graph_id}) — {len(row.query or '')} chars of Cypher")
        self.stdout.write("Rebuild each through the builder; see docs/VOCABULARY.md §3.")
