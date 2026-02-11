"""
Assertion query resolvers.
"""

from kante.types import Info
import strawberry

from api import types, context, inputs
from core import models


def render_graph_nodes(
    info: Info,
    query: strawberry.ID,
    filters: inputs.RenderGraphNodesFilter | None = None,
    pagination: inputs.RenderGraphNodesPagination | None = None,
    order: inputs.RenderGraphNodesOrder | None = None,
) -> types.GraphNodesRender:
    """
    Fetch the assertion (provenance) that generated an entity.

    Args:
        info: Strawberry Info context
        graph_query: The ID of the graph query

    Returns:
        Assertion object or None if not found
    """

    controller = context.get_controller()

    graph_query = models.GraphNodesQuery.objects.get(id=query)  # Validate graph query exists

    filters_model = filters.to_pydantic() if filters else None
    pagination_model = pagination.to_pydantic() if pagination else None
    order_model = order.to_pydantic() if order else None

    response = controller.render_graph_nodes_query(graph_query, filters=filters_model, pagination=pagination_model, order=order_model)

    return types.GraphNodesRender(_value=response)
