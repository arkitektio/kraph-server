"""
Entity query resolvers.
"""

from typing import List
from kante.types import Info
import strawberry

from api import types, context, inputs


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


def entities_informed_by(
    info: Info,
    graph: str,
    identifier: str,
    object: str,
) -> List[types.Entity]:
    """
    Fetch all entities that are informed by a given structure.

    Args:
        info: Strawberry Info context
        identifier: Structure identifier (e.g. '@mikro/roi')
        object: Structure object ID

    Returns:
        List of Entity objects
    """
    controller = context.get_controller()
    responses = controller.get_entities_informed_by(
        identifier=identifier,
        structure_object=object,
    )
    return [types.Entity(_value=r) for r in responses]
