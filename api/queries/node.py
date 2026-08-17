"""Node query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, filters, order, pagination, types
from api.queries import _nodes
from graph_engine import input_models, scalars


def nodes(
    info: Info,
    graph: strawberry.ID,
    filters: filters.NodeFilters | None = None,
    ordering: list[order.NodeOrder] | None = None,
    pagination: pagination.NodePaginationInput | None = None,
) -> List[types.Node]:
    """Every node this view holds, from the claims.

    View-scoped, which is what a `graph` argument means: membership is
    `projector.refs_in_graph` — the graph's own categories and definitions, folded
    over the existence claims its selector counts — and the drawing supplies the
    properties where there is one.

    This used to be `controller.list_entities`, which matched vertices whose label
    was one of the graph's **entity** categories, so *nodes* silently meant entities:
    an event drawn in the same view never appeared. Nor did an admitted node the
    projection had not caught up with.
    """
    controller = context.get_controller()

    graph_model = context.get_accessible_graph(info, graph)

    filter_model = filters.to_pydantic() if filters else input_models.NodeFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.NodePagination()

    rows = _nodes.narrow(_nodes.rows_in_graph(graph_model), filter_model, ordering_models, pagination_model)

    return [types.Node.to_subtype(node) for node in _nodes.retrieved_in(controller, graph_model, rows)]


def node(info: Info, id: scalars.GraphID, graph: strawberry.ID) -> types.Node:
    """One node, as the named view holds it.

    A `Node` is a drawing shape — label, category, derived properties — and every
    one of those is *some view's* answer, so the view has to be named. This used
    to take no graph and answer from `drawings[0]`: whichever view
    `graphs_for_refs` yielded first, with nothing on the result saying which.

    Same contract as `nodes(graph:)`, one node at a time: admitted but not yet
    drawn comes back as the bare row shape (`schemaVersion` null), and a node
    this view does not admit is refused. The claim itself, for a node no view
    admits, is `instance(id:)`.
    """
    controller = context.get_controller()
    graph_model = context.get_accessible_graph(info, graph)
    instance = controller._resolve_instance(str(id), info)
    return types.Node.to_subtype(_nodes.one_in_graph(controller, graph_model, instance))
