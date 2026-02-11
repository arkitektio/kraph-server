"""
Entity query resolvers.
"""

from typing import List
from kante.types import Info
import strawberry

from api import types, context, inputs
from core import models


def entities(info, filters: inputs.EntityFilterInput | None = None, order: inputs.EntityOrderInput | None = None) -> List[types.Entity]:
    raise NotImplementedError("This resolver is not implemented yet")


def entity(info: Info, id: str) -> types.Entity:
    """
    Fetch a single entity by its Global ID.

    Args:
        info: Strawberry Info context
        id: The entity's string ID

    Returns:
        Entity object
    """
    controller = context.get_controller()
    response = controller.get_node_for_composite_id(composite_id=id)
    return types.Entity(_value=response)


def entities_informed_by(info: Info, id: strawberry.ID) -> List[types.Entity]:
    """
    Fetch all entities that are informed by a given structure.

    Args:
        info: Strawberry Info context
        id: The composite ID of the structure (format: "graph_id:node_id")

    Returns:
        List of Entity objects
    """
    controller = context.get_controller()

    graph = context.extract_graph_id(id)
    identifier = context.extract_node_id(id)

    models.Graph.objects.get(id=graph)  # Validate graph exists

    structures = controller.get_entities_informed_by_structure(graph_id=graph, structure_id=identifier)

    return [types.Entity(_value=r) for r in structures]
