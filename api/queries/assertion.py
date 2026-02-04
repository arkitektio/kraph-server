"""
Assertion query resolvers.
"""
from typing import Optional
from kante.types import Info

from api.types import Assertion, assertion_from_response
from api.context import get_controller_for_node_id


def assertion_for_entity(
    info: Info,
    entity_id: str,
) -> Optional[Assertion]:
    """
    Fetch the assertion (provenance) that generated an entity.
    
    Args:
        info: Strawberry Info context
        entity_id: The entity's string ID
        
    Returns:
        Assertion object or None if not found
    """
    controller = get_controller_for_node_id(entity_id, info)
    response = controller.get_assertion_for_entity(entity_id=entity_id)
    if response is None:
        return None
    return assertion_from_response(response)
