"""
Structure query resolvers.
"""
from typing import Optional, List
from kante.types import Info

from api.types import Structure, structure_from_response
from api.context import get_controller_from_context


def structure(
    info: Info,
    identifier: str,
    object: str,
) -> Optional[Structure]:
    """
    Fetch a specific structure by its identifier and object ID.
    
    Args:
        info: Strawberry Info context
        identifier: Structure identifier (e.g. '@mikro/roi')
        object: Structure object ID
        
    Returns:
        Structure object or None if not found
    """
    controller = get_controller_from_context(info)
    response = controller.get_structure(identifier=identifier, object=object)
    if response is None:
        return None
    return structure_from_response(response)


def informing_structures(
    info: Info,
    entity_id: str,
) -> List[Structure]:
    """
    Fetch all structures that inform a given entity.
    
    Args:
        info: Strawberry Info context
        entity_id: The entity's string ID
        
    Returns:
        List of Structure objects
    """
    controller = get_controller_from_context(info)
    responses = controller.get_informing_structures(entity_id=entity_id)
    return [structure_from_response(r) for r in responses]
