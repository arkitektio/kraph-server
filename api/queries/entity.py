"""
Entity query resolvers.
"""
from typing import List
from kante.types import Info

from api.types import Entity, entity_from_response
from api.context import get_controller_from_context


def entity(info: Info, id: str) -> Entity:
    """
    Fetch a single entity by its ID.
    
    Args:
        info: Strawberry Info context
        id: The entity's string ID
        
    Returns:
        Entity object
    """
    controller = get_controller_from_context(info)
    response = controller.get_entity(id=id)
    return entity_from_response(response)


def entities_informed_by(
    info: Info,
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
    controller = get_controller_from_context(info)
    responses = controller.get_entities_informed_by(
        identifier=identifier,
        structure_object=object,
    )
    return [entity_from_response(r) for r in responses]
