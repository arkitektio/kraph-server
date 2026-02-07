"""
Entity query resolvers.
"""
from typing import List
from kante.types import Info

from api.types import Entity, entity_from_response
from api.context import get_controller


def entity(info: Info, id: str) -> Entity:
    """
    Fetch a single entity by its Global ID.
    
    Args:
        info: Strawberry Info context
        id: The entity's string ID
        
    Returns:
        Entity object
    """
    controller = get_controller()
    response = controller.get_node_for_composite_id(composite_id=id)
    return entity_from_response(response)


def entities_informed_by(
    info: Info,
    graph: str,
    identifier: str,
    object: str,
) -> List[Entity]:
    """
    Fetch all entities that are informed by a given structure.
    
    Args:
        info: Strawberry Info context
        identifier: Structure identifier (e.g. '@mikro/roi')
        object: Structure object ID
        
    Returns:
        List of Entity objects
    """
    controller = get_controller()
    responses = controller.get_entities_informed_by(
        identifier=identifier,
        structure_object=object,
    )
    return [entity_from_response(r) for r in responses]
