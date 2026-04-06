"""
Entity query resolvers.
"""

from typing import List
from kante.types import Info
import strawberry

from api import types, context, inputs, filters, order, pagination
from core import models
from graph_engine import scalars
from graph_engine import input_models


def _coerce_filter_value(value):
    if not isinstance(value, str):
        return value

    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"

    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def nodes(
    info: Info,
    graph: strawberry.ID,
    filters: filters.NodeFilters | None = None,
    ordering: list[order.NodeOrder] | None = None,
    pagination: pagination.NodePaginationInput | None = None,
) -> List[types.Node]:
    controller = context.get_controller()

    graph_model = context.get_accessible_graph(info, graph)

    filter_model = filters.to_pydantic() if filters else input_models.NodeFilters()

    ordering_models = [order.to_pydantic() for order in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.NodePagination()

    result = controller.list_entities(
        graph=graph_model,
        filters=filter_model,
        pagination=pagination_model,
        ordering=ordering_models,
        info=info,
    )

    return [types.Node.to_subtype(entity) for entity in result]


def node(info: Info, id: scalars.GraphID) -> types.Node:
    """
    Fetch a single node by its Global ID.

    Args:
        info: Strawberry Info context
        id: The node's string ID

    Returns:
        Node object
    """
    controller = context.get_controller()
    response = controller.get_node_for_composite_id(composite_id=id, info=info)
    return types.Node.to_subtype(response)
