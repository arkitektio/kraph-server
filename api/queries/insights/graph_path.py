"""
Assertion query resolvers.
"""

from typing import Optional
from kante.types import Info
import strawberry

from api import types, context, inputs
from core import models


def render_graph_path(
    info: Info,
    query: strawberry.ID,
    filters: inputs.RenderGraphPathFilter | None = None,
    pagination: inputs.RenderGraphPathPagination | None = None,
    order: inputs.RenderGraphPathOrder | None = None,
) -> Optional[types.Assertion]:
    """
    Fetch the assertion (provenance) that generated an entity.

    Args:
        info: Strawberry Info context
        graph_query: The ID of the graph query

    Returns:
        GraphPathRender object or None if not found
    """

    controller = context.get_controller()

    graph_query = models.GraphPathQuery.objects.get(id=query)  # Validate graph query exists

    filters_model = filters.to_pydantic() if filters else None
    pagination_model = pagination.to_pydantic() if pagination else None
    order_model = order.to_pydantic() if order else None

    response = controller.render_graph_path_query(graph_query, filters=filters_model, pagination=pagination_model, order=order_model, info=info)

    return types.GraphPathRender(_value=response)
