"""What a projection kind has to be able to do.

Two halves, one protocol. The **writer** half is what `graph_engine.projector`
calls to draw the evidence — one vertex per individual (a component of
instances the view holds to be one thing, RFC 0018), one edge per proposition,
derived properties on the vertex — and what `rebuild` calls to drop and recreate
a view's namespace. The **reader** half is what the API asks for a *drawing*:
the nodes a view has drawn, whether it drew an edge, and (for saved queries) a
rendered table.

Everything here is phrased in the vocabulary of the evidence and the schema —
refs, labels, category ids, property dicts, and (for the list read) a
structured predicate — and nothing in the vocabulary of a storage engine or a
query language. Labels are `Category.age_name`: the view's own word for a
category. Vertex and edge ids are opaque integers that a rebuild reassigns;
they are carried only because `RetrievedNode`/`RetrievedEdge` still name them,
and nothing keys on them.

`controller.engine` is gone, and so is the controller's habit of writing
queries itself: the seven places it executed Cypher directly — two of them
*writes* (`DELETE r` for a retracted relation or participation) — are the
methods below. `graph_engine.projector` imports no engine and no query language;
it calls `controller.projector.<method>`. `list_drawn` used to be the one
method that still took query-language fragments (a Cypher predicate, an ORDER
BY clause, a SKIP/LIMIT string, built by the controller); it takes a
:class:`ListDrawnSpec` now, and each projection kind compiles it itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from evidence.values import JSONValue

if TYPE_CHECKING:
    # Annotations only, and deliberately so: this module is the seam a second
    # projection kind implements, so it must name the schema's rows and the
    # plan's shape without importing Django or the query compiler at runtime.
    from core.models import Graph
    from graph_engine.input_models import RenderGraphTableFilter, RenderGraphTableOrder, RenderGraphTablePagination
    from graph_engine.query_ir import TableQueryPlan


@dataclass(frozen=True)
class DrawnEdge:
    """The ids an implementation gives an edge it has drawn. Opaque; never identity."""

    edge_id: int
    left_id: int
    right_id: int


@dataclass(frozen=True)
class IncidentEdgesSpec:
    """Which drawn edges touching a vertex to list — as data, compiled by the kind."""

    #: Edge labels to keep; empty means every label.
    labels: tuple[str, ...] = ()
    #: "OUT" (the vertex is the source), "IN" (the target) or "BOTH".
    direction: str = "BOTH"
    #: Hard cap per asked ref; the API pages below it.
    limit: int = 1000


@dataclass(frozen=True)
class IncidentEdge:
    """One drawn edge touching an asked vertex. Ids opaque; refs are the endpoints' representatives."""

    edge_id: int
    label: str
    source_id: int
    target_id: int
    source_ref: str
    target_ref: str
    properties: Mapping[str, JSONValue]


#: The comparisons a drawing-scoped list may ask for. The canonical spellings —
#: the controller normalizes its API's aliases (``EQ``, ``=``, …) before a spec
#: is built, so an implementation compiles exactly these and refuses the rest.
LIST_OPERATORS = frozenset({"EQUALS", "NOT_EQUALS", "GREATER_THAN", "LESS_THAN", "GREATER_OR_EQUAL", "LESS_OR_EQUAL", "IN", "NOT_IN", "CONTAINS", "STARTS_WITH", "ENDS_WITH", "IS_NOT_NULL"})


@dataclass(frozen=True)
class PropertyPredicate:
    """One comparison against a drawn node's record.

    `key` names a property of the drawn record: a derived property, or one of
    the identity trio — ``id`` (the node's uuid), ``category_ids`` (every
    category the view draws it under, RFC 0019 — ``EQUALS``/``IN`` ask whether
    the value is *among* them), ``type``.
    ``IS_NOT_NULL`` takes no value and means *the view derived this key for
    this node* — a key present with an explicit null does not count, matching
    what the Cypher form (`e.key IS NOT NULL`) always meant.
    """

    key: str
    operator: str = "EQUALS"
    value: JSONValue = None


@dataclass(frozen=True)
class DrawnNode:
    """One vertex as a view has drawn it — the reader half's unit.

    Was `dict[str, Any]`, which made the record's own contract unreadable: the
    keys were documented in three prose docstrings, `RetrievedNode.from_node`
    guessed at four of them with `.get(...)` fallbacks, and a caller could not
    tell `properties["id"]` — the individual's representative, which is real
    identity and may differ from the key the record sits under — from `id`, the
    drawing's opaque vertex id, which a reproject reassigns.

    `labels` is every label the vertex is drawn under, sorted; `label` is the
    first, for a reader that shows one (RFC 0019). `members` is every instance
    the vertex stands for (RFC 0018), `properties["id"]` the representative
    among them.
    """

    #: The drawing's own vertex id. Opaque, reassigned by every reproject,
    #: never identity — that is `properties["id"]`.
    id: int
    label: str
    labels: tuple[str, ...] = ()
    properties: Mapping[str, JSONValue] = field(default_factory=dict)
    members: tuple[str, ...] = ()


@dataclass(frozen=True)
class DrawnOrder:
    """One sort key for a drawing-scoped list.

    `key` is a property key as in :class:`PropertyPredicate`, or the sentinel
    ``__internal_id`` — the drawing's own opaque vertex id, which orders by
    draw order and is the successor of the Cypher ``id(e)`` ordering.
    """

    key: str
    descending: bool = False


@dataclass(frozen=True)
class ListDrawnSpec:
    """What `list_drawn` is asked: predicates, order, page — as data, not clauses.

    `label` scopes the list to one category's word, exactly as the old
    label-in-the-MATCH-pattern did. Every field is storage-agnostic; the
    projection kind compiles it. Predicates are conjunctive.
    """

    label: str
    predicates: tuple[PropertyPredicate, ...] = ()
    order: tuple[DrawnOrder, ...] = ()
    offset: int = 0
    limit: int = 200


@runtime_checkable
class Projector(Protocol):
    """One projection kind: how a view is drawn and read back."""

    # ------------------------------------------------------------------ namespace

    def refresh_namespace(self, graph: Graph) -> None:
        """(Re)derive the place this graph's drawing is queried from, from the view's categories.

        Idempotent and re-runnable: the namespace is a **derived artifact**,
        rebuilt wholesale from `Category` rows exactly as the drawing is rebuilt
        from evidence (RFC 0006). Called after materialize declares the
        categories, after a rebuild's drop, and by the category-write signal.
        """
        ...

    def drop_namespace(self, graph: Graph) -> None:
        """Destroy the drawing, its namespace, and everything in them. The evidence is untouched by construction."""
        ...

    def validate_plan(self, plan: TableQueryPlan) -> None:
        """Refuse a structurally invalid saved-query plan — the save-time check, no view in scope."""
        ...

    # ------------------------------------------------------------------ writer: nodes

    def draw_node(self, graph: Graph, ref: str, categories: Sequence[tuple[str, int]], kind: str, members: Iterable[str]) -> None:
        """Draw (or re-draw) one node under every `(label, category_id)` in `categories`, carrying `{id, category_ids, type}`, standing for `members`.

        `ref` is the individual's representative and `members` every instance
        the vertex stands for — `ref` among them. Any member addresses the vertex
        afterwards: as an edge endpoint, in `drawn_nodes`, in `erase_nodes`.
        `categories` is non-empty: a vertex is drawn under at least one category
        (RFC 0019), and one drawn under several is **one** vertex with several
        labels. Converging: drawing a ref that is already drawn leaves one
        vertex, and both the label set and the member list are **replaced**,
        not merged. It does **not** move a node between individuals — the
        caller clears first (`erase_nodes`) when membership may have changed.
        """
        ...

    def write_properties(self, graph: Graph, ref: str, values: Mapping[str, JSONValue]) -> bool:
        """Set derived properties on the drawn node holding `ref`. Returns whether the node was there to write onto.

        A `None` value **removes** the key: a derived property whose evidence no
        longer supports it has no value, and the drawing must not keep the last
        number it had (RFC 0023).
        """
        ...

    def clear_properties(self, graph: Graph, label: str, refs: Iterable[str], keys: Iterable[str]) -> None:
        """Remove these property keys from these drawn nodes, where drawn under `label`. The sweep before a redraw."""
        ...

    def erase_nodes(self, graph: Graph, refs: Iterable[str]) -> int:
        """Remove every node holding any of these refs as a member, and every edge touching it. Returns how many nodes were there."""
        ...

    # ------------------------------------------------------------------ writer: edges

    def draw_edge(self, graph: Graph, source_ref: str, target_ref: str, label: str, properties: Mapping[str, JSONValue]) -> bool:
        """Draw (or re-draw) one edge source → target under `label`, setting `properties`.

        Either endpoint may be any member of its individual; the edge lands on
        the vertices those members belong to. Converging on `(source, target,
        label)`. Returns False when an endpoint is not drawn, in which case
        nothing was written — the caller decides whether that is worth a warning.
        """
        ...

    def erase_edge(self, graph: Graph, source_ref: str, target_ref: str, label: str, match: Mapping[str, JSONValue] | None = None) -> None:
        """Remove the edge source → target under `label` whose properties match `match` (if given)."""
        ...

    # ------------------------------------------------------------------ writer: keys

    def validate_key(self, key: str) -> str:
        """Refuse a property key this projection cannot store or that could not be written safely."""
        ...

    # ------------------------------------------------------------------ reader

    def drawn_nodes(self, graph: Graph, refs: Iterable[str]) -> dict[str, DrawnNode]:
        """The drawn records for these refs, keyed by the ref **asked for**; a missing key means undrawn.

        Several asked refs may share one record: members of one individual. The
        record's `properties["id"]` is the representative, which may differ from
        the key it sits under. `labels` is every label the vertex is drawn
        under, sorted; `label` is the first of them, for a reader that shows
        one (RFC 0019).
        """
        ...

    def drawn_edges_incident(self, graph: Graph, refs: Iterable[str], spec: IncidentEdgesSpec) -> dict[str, list[IncidentEdge]]:
        """Every drawn edge touching the vertex holding each ref, keyed by the ref **asked for**.

        Any member addresses its vertex (RFC 0018). A self-edge appears once. A
        ref the view has not drawn is absent from the answer.
        """
        ...

    def drawn_edge(self, graph: Graph, source_ref: str, target_ref: str, label: str) -> DrawnEdge | None:
        """The ids of the edge source → target under `label`, or None if this view does not draw it."""
        ...

    def list_drawn(self, graph: Graph, spec: ListDrawnSpec) -> list[DrawnNode]:
        """The drawn records matching `spec` — the drawing-scoped list, compiled by the kind."""
        ...

    def render_table(self, graph: Graph, plan: TableQueryPlan, *, filters: RenderGraphTableFilter | None = None, order: RenderGraphTableOrder | None = None, pagination: RenderGraphTablePagination | None = None) -> list[dict[str, JSONValue]]:
        """Compile a `TableQueryPlan` for this projection kind, run it, and hand back its rows."""
        ...
