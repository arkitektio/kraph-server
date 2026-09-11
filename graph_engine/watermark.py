"""The projection cursor: how far along the log a view's drawing is, and why it is safe.

Definitions, for one graph ``G`` in organization ``O``::

    max_seq(O)         = Max(Assertion.seq) over O            (0 when O has no assertions)
    min_pending_seq(O) = Min(PendingProjection.assertion.seq) over O, or None

    cursor(G) = 0                                              if G.projection.status != CONSISTENT
              = min(min_pending_seq(O) - 1, max_seq(O))       otherwise; max_seq(O) when nothing is pending

    lag(G)    = max_seq(O) - cursor(G)

**Invariant**: for a consistent graph, every committed assertion with
``seq <= cursor(G)`` has been applied to G's drawing. Claims recorded before the
last bulk operation read the log were applied by that operation; claims after it
were applied by their own writer, which either enumerated G through
`projector.graphs_for_refs` and succeeded — and then deleted its outbox row — or
raised and left the row, which pulls the cursor below it. An assertion whose
transaction is still open when somebody reads the cursor either rolls back, or
commits *together with* its outbox row, which immediately pulls the cursor under
it. So neither of the two hazards a bare ``seq > N`` scan has — the
uncommitted lower seq, and the commit-then-crash — can put a claim above the
cursor that the drawing has not seen.

The cursor is therefore **derived**, never stored. Storing a per-graph
"applied through" that a write advanced was the first design, and it recorded a
value that was not yet true. What *is* stored is `Projection.derived_through_seq`,
which is informational — the log position a bulk operation read at — and the
`status`, which is what turns an un-backfilled or half-rebuilt graph into an
honest "everything is outstanding".

Schema edits carry no `seq` at all — a category's rules moving is not a claim —
so staleness of that kind is a separate axis: `schema_stale`, compared against
`GraphSchema.active_for(graph).hash`.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from authentikate.models import Organization
from core.models import Graph
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone

from evidence import models as evidence_models
from graph_engine import models as projection_models


def projection_for(graph: Graph) -> projection_models.Projection:
    """The bookkeeping row for a graph, created on first sight.

    `get_or_create` rather than a signal, so a `Graph` row made straight through
    the ORM — fixtures, the admin, a shell — gets one the first time anything asks,
    in the honest default state: `NEEDS_BACKFILL`, since nothing has drawn it.
    """
    row, _ = projection_models.Projection.objects.get_or_create(graph=graph)
    return row


def max_seq(organization: Organization) -> int:
    """The highest assertion seq the organization has committed; 0 when none."""
    value = evidence_models.Assertion.objects.for_organization(organization).aggregate(value=Max("seq"))["value"]
    return int(value or 0)


def min_pending_seq(organization: Organization) -> int | None:
    """The lowest outstanding assertion seq, or None when nothing is pending."""
    value = projection_models.PendingProjection.objects.filter(organization=organization).aggregate(value=Min("assertion__seq"))["value"]
    return int(value) if value is not None else None


def pending_count(organization: Organization) -> int:
    """How many assertions nobody has finished drawing."""
    return projection_models.PendingProjection.objects.filter(organization=organization).count()


@dataclass(frozen=True)
class Position:
    """Where one graph's drawing stands relative to its organization's log."""

    status: str
    cursor: int
    lag: int
    pending: int
    max_seq: int
    derived_through_seq: int
    schema_hash: str | None
    schema_stale: bool
    derived_at: datetime.datetime | None
    rebuilt_at: datetime.datetime | None


def cursor_from(status: str, organization_max_seq: int, organization_min_pending: int | None) -> int:
    """The cursor, from the three numbers it depends on. Pure, so it can be tested alone."""
    if status != projection_models.Projection.Status.CONSISTENT:
        return 0
    if organization_min_pending is None:
        return organization_max_seq
    return min(organization_min_pending - 1, organization_max_seq)


def schema_stale(graph: Graph, row: projection_models.Projection | None = None) -> bool:
    """Were this graph's vertices last derived under a schema that is no longer the active one?

    A graph with no active schema is never stale: there is no version to be
    behind. A graph whose projection has never recorded a hash *is* stale when a
    schema exists — nothing has derived under it yet.
    """
    from core import models as core_models

    active = core_models.GraphSchema.active_for(graph)
    if active is None:
        return False
    row = row or projection_for(graph)
    return row.schema_hash != active.hash


def position(graph: Graph) -> Position:
    """Everything `Graph.projection` reports, computed once."""
    row = projection_for(graph)
    organization = graph.organization
    top = max_seq(organization)
    lowest_pending = min_pending_seq(organization)
    where = cursor_from(row.status, top, lowest_pending)
    return Position(
        status=str(row.status),
        cursor=where,
        lag=top - where,
        pending=pending_count(organization),
        max_seq=top,
        derived_through_seq=int(row.derived_through_seq),
        schema_hash=row.schema_hash,
        schema_stale=schema_stale(graph, row),
        derived_at=row.derived_at,
        rebuilt_at=row.rebuilt_at,
    )


def positions(graphs: Iterable[Graph]) -> dict[int, Position]:
    """`position` for many graphs, with the per-organization numbers computed once each."""
    graphs = list(graphs)
    rows = {row.graph_id: row for row in projection_models.Projection.objects.filter(graph__in=graphs)}
    by_org: dict[int, tuple[int, int | None, int]] = {}
    out: dict[int, Position] = {}
    for graph in graphs:
        row = rows.get(graph.pk) or projection_for(graph)
        org_key = graph.organization_id
        if org_key not in by_org:
            by_org[org_key] = (max_seq(graph.organization), min_pending_seq(graph.organization), pending_count(graph.organization))
        top, lowest_pending, outstanding = by_org[org_key]
        where = cursor_from(row.status, top, lowest_pending)
        out[graph.pk] = Position(
            status=str(row.status),
            cursor=where,
            lag=top - where,
            pending=outstanding,
            max_seq=top,
            derived_through_seq=int(row.derived_through_seq),
            schema_hash=row.schema_hash,
            schema_stale=schema_stale(graph, row),
            derived_at=row.derived_at,
            rebuilt_at=row.rebuilt_at,
        )
    return out


# ---------------------------------------------------------------------------
# Writers. Each is the one place a particular transition happens.
# ---------------------------------------------------------------------------


def expect(assertion: evidence_models.Assertion) -> None:
    """Record that this assertion's projection is owed. Call **inside** the evidence transaction."""
    projection_models.PendingProjection.objects.get_or_create(assertion=assertion, defaults={"organization": assertion.organization})


def settle(assertion: evidence_models.Assertion) -> None:
    """This assertion's synchronous projection finished everywhere it was owed; clear its row.

    By id, never by seq — see :class:`graph_engine.models.PendingProjection`.
    """
    projection_models.PendingProjection.objects.filter(pk=assertion.pk).delete()


def settle_many(assertion_ids: Iterable[uuid.UUID]) -> int:
    """Clear exactly these outbox rows — the ones an incremental replay read and applied."""
    ids = list(assertion_ids)
    if not ids:
        return 0
    deleted, _ = projection_models.PendingProjection.objects.filter(pk__in=ids).delete()
    return int(deleted)


def mark_rebuilding(graph: Graph) -> projection_models.Projection:
    """The namespace is about to be dropped; until the replay finishes, everything is outstanding."""
    row = projection_for(graph)
    row.status = projection_models.Projection.Status.REBUILDING
    row.save(update_fields=["status"])
    return row


def mark_consistent(graph: Graph, *, through_seq: int, schema_hash: str | None, rebuilt: bool = False) -> projection_models.Projection:
    """A bulk operation finished: the drawing reflects the log up to `through_seq` under `schema_hash`."""
    row = projection_for(graph)
    row.status = projection_models.Projection.Status.CONSISTENT
    row.derived_through_seq = max(int(row.derived_through_seq), int(through_seq))
    row.schema_hash = schema_hash
    now = timezone.now()
    row.derived_at = now
    fields = ["status", "derived_through_seq", "schema_hash", "derived_at"]
    if rebuilt:
        row.rebuilt_at = now
        fields.append("rebuilt_at")
    row.save(update_fields=fields)
    return row


def mark_derived(graph: Graph) -> None:
    """`projector.project` wrote properties here just now. One UPDATE per call, not per node."""
    projection_models.Projection.objects.filter(graph=graph).update(derived_at=timezone.now())


def record_schema_hash(graph: Graph, schema_hash: str | None) -> None:
    """Every node category of this graph has been redrawn under `schema_hash`."""
    row = projection_for(graph)
    row.schema_hash = schema_hash
    row.save(update_fields=["schema_hash"])


def active_schema_hash(graph: Graph) -> str | None:
    """The hash a drawing made right now would be derived under."""
    from core import models as core_models

    active = core_models.GraphSchema.active_for(graph)
    return active.hash if active is not None else None


__all__ = [
    "Position",
    "active_schema_hash",
    "cursor_from",
    "expect",
    "mark_consistent",
    "mark_derived",
    "mark_rebuilding",
    "max_seq",
    "min_pending_seq",
    "pending_count",
    "position",
    "positions",
    "projection_for",
    "record_schema_hash",
    "schema_stale",
    "settle",
    "settle_many",
]
