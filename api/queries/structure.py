"""
Structure query resolvers.
"""

from typing import Optional, List
from kante.types import Info

from api import types, context
from core import models


def structure(
    info: Info,
    identifier: str,
    object: str,
) -> Optional[types.Structure]:
    """
    Fetch a specific structure by its identifier and object ID.

    Args:
        info: Strawberry Info context
        identifier: Structure identifier (e.g. '@mikro/roi')
        object: Structure object ID

    Returns:
        Structure object or None if not found
    """
    controller = context.get_controller
    response = controller.get_structure(identifier=identifier, object=object)

    return types.Structure(_value=response)


def informing_structures(
    info: Info,
    entity_id: str,
) -> List[types.Structure]:
    """
    Fetch all structures that inform a given entity.

    Args:
        info: Strawberry Info context
        entity_id: The entity's string ID

    Returns:
        List of Structure objects
    """
    controller = context.get_controller()

    graph_id = context.extract_graph_id(entity_id)
    node_id = context.extract_node_id(entity_id)

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    responses = controller.get_informing_structures(graph, entity_id=entity_id)
    return [types.Structure(_value=r) for r in responses]
