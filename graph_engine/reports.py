"""What a draw reports: how much of a view was redrawn, and what a replay owed.

These were `dict[str, int]` and `dict[str, Any]`, and the dictionary was doing
two jobs it is bad at. It was the **shape**: `project_all` returned six keys,
`converge` six *different* ones, and `rebuild` those plus two more, so a caller
holding "the counts" could not know which keys it had without knowing which
function had produced them — `counts.get("unclassified")` in the controller is
that uncertainty written down. And it was the **type**: `refs` an int, `graphs`
a list of dicts each mixing a `Graph` row with five integers, `skipped` a list
of dicts with a row and a string. `dict[str, Any]` is what you write when the
values have nothing in common, and it hands the reader nothing.

So: one :class:`DrawCounts` with every field a draw can report, zero where an
operation does not answer that question, and a :class:`ReplayReport` whose
per-graph entries are rows rather than dictionaries. Nothing here decides
anything — they are the shapes the projector and the runner hand back, and the
`manage.py reproject` output is read off them field by field.

`claims` and `states` are filled by :func:`graph_engine.projector.rebuild`
alone: they count the organization-wide refolds a full rebuild does first, which
an incremental converge deliberately does not do.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from core import models as core_models


@dataclass(frozen=True)
class DrawCounts:
    """How much of one view was drawn by one operation.

    Every field is zero unless the operation answers that question, so the shape
    is the same whichever of the three drawing entry points produced it.
    """

    #: Nodes the view's rules admitted — the size of `resolve_categories`' answer.
    nodes: int = 0
    #: Individuals those nodes folded into (RFC 0018); one vertex each.
    individuals: int = 0
    #: Nodes **no** category of this view admitted, reported rather than swallowed:
    #: a definition that narrows a category also shrinks the graph, and a caller
    #: that cannot see by how much cannot tell a deliberate selection from a
    #: broken one. Zero from `converge`, which is scoped to refs it was given.
    unclassified: int = 0
    #: Relation edges drawn.
    edges: int = 0
    #: Participation edges drawn.
    participations: int = 0
    #: Nodes whose derived properties were written.
    projected: int = 0
    #: Vertices removed first, so a redraw converges. Only `converge` erases.
    erased: int = 0
    #: Cached standings refolded before the drawing was read. `rebuild` only.
    claims: int = 0
    #: State vectors refolded before the drawing was read. `rebuild` only.
    states: int = 0

    def with_refolds(self, *, claims: int, states: int) -> DrawCounts:
        """The same counts, plus what a full rebuild refolded before drawing."""
        return replace(self, claims=claims, states=states)


@dataclass(frozen=True)
class GraphReplay:
    """One consistent view a replay applied its outstanding assertions to."""

    graph: core_models.Graph
    counts: DrawCounts


@dataclass(frozen=True)
class SkippedGraph:
    """One view a replay left alone, and why.

    A `NEEDS_BACKFILL` or `REBUILDING` graph needs a full `reproject --graph`;
    a partial redraw of an undrawn view would only make its lag dishonest.
    """

    graph: core_models.Graph
    status: str


@dataclass(frozen=True)
class ReplayReport:
    """What one pass of `reproject --incremental` did for one organization."""

    #: Outbox rows this pass read — and, since it settles exactly what it read,
    #: the number it settled unless somebody else got there first.
    pending: int
    #: Outbox rows actually deleted.
    settled: int
    #: The lowest `seq` among the rows read, or None when nothing was owed.
    lowest_seq: int | None
    #: The log head this pass marked the processed graphs consistent through.
    head: int
    #: How many refs the outstanding assertions touched, widened to whole
    #: individuals.
    refs: int
    graphs: tuple[GraphReplay, ...] = ()
    skipped: tuple[SkippedGraph, ...] = ()


__all__ = ["DrawCounts", "GraphReplay", "ReplayReport", "SkippedGraph"]
