"""
Assertion query resolvers.
"""

from typing import Optional
from kante.types import Info

from api import types, context
from core import models


def assertion_for_entity(
    info: Info,
    entity_id: str,
) -> Optional[types.Assertion]:
    """
    Fetch the assertion (provenance) that generated an entity.

    Args:
        info: Strawberry Info context
        entity_id: The entity's string ID

    Returns:
        Assertion object or None if not found
    """
    controller = context.get_controller()

    graph_id = context.extract_graph_id(entity_id)
    context.extract_node_id(entity_id)

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    response = controller.get_assertions_for_entity(graph, entity_id=entity_id)
    if response is None:
        return None
    return types.Assertion(_value=response)
