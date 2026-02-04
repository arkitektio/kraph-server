"""
Entity mutation resolvers.
"""
from kante.types import Info

from api.types import Entity, EntityCreationResult, entity_from_response
from api.inputs import EntityCreationInput
from api.context import get_controller_from_context
from graph_engine import input_models


def create_entity(
    info: Info,
    input: EntityCreationInput,
) -> EntityCreationResult:
    """
    Create a new entity with optional supporting evidence structures.
    
    Properties are automatically derived from the evidence according to
    the graph schema rules.
    
    Args:
        info: Strawberry Info context
        input: EntityCreationInput (pydantic-validated)
        
    Returns:
        EntityCreationResult with the created entity
    """
    controller = get_controller_from_context(info)
    
    # Convert strawberry-pydantic input to pydantic model
    payload = input.to_pydantic()
    
    result = controller.create_entity(payload)
    
    # Fetch the created entity for the response
    entity_response = controller.get_entity(id=result.db_id)
    entity = entity_from_response(entity_response)
    
    return EntityCreationResult(
        ref_id=result.ref_id,
        db_id=result.db_id,
        graph_id=result.graph_id,
        status=result.status,
        entity=entity,
    )


def recalculate_entity(
    info: Info,
    entity_id: str,
) -> Entity:
    """
    Force recalculation of an entity's derived properties.
    
    This is useful after batch linking operations where
    recalculate was set to False.
    
    Args:
        info: Strawberry Info context
        entity_id: The entity's string ID
        
    Returns:
        Updated Entity with recalculated properties
    """
    controller = get_controller_from_context(info)
    
    # Get entity first to find its graph_id and kind
    entity = controller.get_entity(id=entity_id)
    
    # Trigger recalculation
    controller._recalculate_entity(
        graph_id=entity.graph_id,
        label=entity.kind,
        schema=controller.definition,
    )
    
    # Return updated entity
    updated_response = controller.get_entity(id=entity_id)
    return entity_from_response(updated_response)




