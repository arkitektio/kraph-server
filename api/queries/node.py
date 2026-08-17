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


def node(info: Info, id: scalars.GraphID) -> types.Node:
    """
    Fetch a single node by its id.

    Args:
        info: Strawberry Info context
        id: The node's uuid

    Returns:
        Node object
    """
    controller = context.get_controller()
    response = controller.get_node(node_id=id, info=info)
    return types.Node.to_subtype(response)
