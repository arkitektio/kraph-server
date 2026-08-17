"""Listing nodes from the evidence base rather than from Apache AGE.

The node-side counterpart of :mod:`api.queries._edges`, and it exists for the same
reason: a list of nodes was a list of *vertices*, so a claim the view admits but has
not drawn yet did not appear in it, and the answer changed when the projection was
rebuilt. A graph is a view; the log is what there is.

**What is view-scoped and what is not.** A category belongs to one graph, so a
category-scoped list is legitimately that view's answer — but the view's *rule* is
what decides membership, not the state of its cache. So membership comes from
`projector.refs_admitted_by`, which routes through `resolve_categories`: the same
function that decides which vertices get drawn, asked without reference to whether
they have been. A node this category admits therefore appears whether or not the
projection is up to date, and it appears with the properties the view derives when
there is a vertex to read them from.

**Filters that only ever meant something against a vertex are refused**, exactly as
`_edges.refuse_vertex_filters` refuses them for edges. `has_property`, `search` and
`matches` ask about derived properties, which live in the drawing and only exist
where the view has drawn the node; ordering by a property is the same question. A
filter that quietly narrows a claim list by what happens to be cached is how a wrong
answer looks right.
"""

from __future__ import annotations

from typing import Any, Iterable

from evidence import models as evidence_models
from graph_engine import projector
from graph_engine.retrieved import RetrievedNode

#: Filters that only ever meant something against a drawn vertex's properties.
_DRAWING_ONLY_FILTERS = ("has_property", "search", "matches")


def refuse_drawing_filters(filter_model: Any, ordering_models: Iterable[Any] = ()) -> None:
    """Reject filters and orderings that only apply to a view's drawing."""
    offending = [name for name in _DRAWING_ONLY_FILTERS if getattr(filter_model, name, None)]
    if any(getattr(order_model, "property", None) for order_model in ordering_models):
        offending.append("property ordering")
    if offending:
        raise ValueError(f"{', '.join(offending)} asks about properties of a projected vertex. Nodes are listed from the evidence log now, and a claim carries no derived properties — a node that no view has drawn has none at all. Filter on `ids`, or ask the drawing through a graph-scoped query.")


def rows_for_category(category: Any) -> Any:
    """Every node this category draws, as `Instance` rows.

    Membership is `projector.refs_admitted_by` — the claims' answer — so this is
    the category's *rule* rather than its cache. `for_organization` on top of an id
    filter is not redundant: the refs came from the graph's own organization, and
    keeping the tenant fence on every read is what makes that true by construction
    rather than by argument.
    """
    graph = category.graph
    refs = projector.refs_admitted_by(category)
    return evidence_models.Instance.objects.for_organization(graph.organization).filter(id__in=refs).select_related("term")


def rows_in_graph(graph: Any) -> Any:
    """Every node this graph holds, as `Instance` rows."""
    refs = projector.refs_in_graph(graph)
    return evidence_models.Instance.objects.for_organization(graph.organization).filter(id__in=refs).select_related("term")


def narrow(rows: Any, filter_model: Any, ordering_models: Iterable[Any], pagination_model: Any) -> list[Any]:
    """Apply the ids filter, the ordering and the page. Returns rows.

    Ordering is over the log's own columns. `created_at` is when the claim was
    recorded; `id` breaks ties deterministically, which `id(n) DESC` over reassigned
    Apache AGE vertex ids never could.
    """
    ordering_models = list(ordering_models)
    refuse_drawing_filters(filter_model, ordering_models)

    if getattr(filter_model, "ids", None):
        rows = rows.filter(pk__in=[str(node_id) for node_id in filter_model.ids])

    order_by: list[str] = []
    for order_model in ordering_models:
        if getattr(order_model, "created_at", None):
            order_by.append(_direction("created_at", order_model.created_at))
        if getattr(order_model, "id", None):
            order_by.append(_direction("id", order_model.id))
    if not order_by:
        order_by = ["-created_at", "-id"]

    offset = int(getattr(pagination_model, "offset", 0) or 0)
    limit = int(getattr(pagination_model, "limit", 100) or 100)
    return list(rows.order_by(*order_by)[offset : offset + limit])


def one_in_graph(controller: Any, graph: Any, instance: Any) -> RetrievedNode:
    """One node, as the named view holds it — the singular form of `rows_in_graph`.

    Refuses a node the view's rule does not admit, so `node(id:, graph:)` succeeds
    exactly when `nodes(graph:)` could list it. Admitted but not yet drawn comes
    back as `RetrievedNode.from_row`, the same as in a list. The claim-grain
    reader — the one that answers for a node no view admits — is `instance(id:)`.
    """
    row = rows_in_graph(graph).filter(pk=str(instance.pk)).first()
    if row is None:
        raise ValueError(f"Graph '{graph.age_name}' does not hold node '{instance.pk}': no category of this view declares or derives from the node's word, or its selector does not count the claim. Read the claim itself with `instance(id:)`, and `Instance.drawnIn` says which views hold it.")
    return retrieved_in(controller, graph, [row])[0]


def retrieved_in(controller: Any, graph: Any, rows: list[Any]) -> list[RetrievedNode]:
    """The nodes as this view holds them, falling back to the log where it holds none.

    One Cypher round-trip for the page, not one per node. A row with no vertex comes
    back as `RetrievedNode.from_row` — the same shape a write returns before anything
    is drawn — so "this view has not drawn it yet" is an object with no derived
    properties rather than a gap in the list.
    """
    if not rows:
        return []

    drawn = controller.drawn_instances(graph, [str(row.pk) for row in rows])
    return [drawn.get(str(row.pk)) or RetrievedNode.from_row(controller, row) for row in rows]


def _direction(column: str, value: Any) -> str:
    return f"-{column}" if str(value).upper().endswith("DESC") else column
