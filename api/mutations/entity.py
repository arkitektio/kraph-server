"""
Entity mutation resolvers.
"""
from kante.types import Info

from api.types import Entity, EntityCreationResult, entity_from_response
from api.inputs import EntityCreationInput, RecalculateEntityInput
from api.context import get_controller_for_graph_id
from core import models




def create_entity(
    info: Info,
    input: EntityCreationInput,
) -> Entity:
    """
    Create a new entity with optional supporting evidence structures.
    
    Properties are automatically derived from the evidence according to
    the graph schema rules.
    
    Args:
        info: Strawberry Info context
        input: EntityCreationInput with graph_id, kind, and evidence
        
    Returns:
        EntityCreationResult with the created entity
    """
    import uuid
    
    
    category = models.EntityCategory.objects.get(id=input.entity_category)  # Validate graph exists
    
    # Get controller for the specified graph (includes provenance from context)
    controller = get_controller_for_graph_id(info)
    
    # Generate ref_id if not provided
    entity_ref_id = input.ref_id or str(uuid.uuid4())
    
    # Convert evidence to list of dicts for the controller
    evidence_list = []
    if input.supporting_evidence:
        for ev in input.supporting_evidence:
            # ev is a StructureReferenceInput (strawberry-pydantic type)
            # Convert to pydantic first, then to dict
            ev_pydantic = ev.to_pydantic()
            ev_dict = {
                "identifier": ev_pydantic.identifier,
                "object": ev_pydantic.object,
                "measurements": [m.model_dump(exclude_none=True) for m in ev_pydantic.measurements],
            }
            evidence_list.append(ev_dict)
            
            
    entity_category = models.EntityCategory.objects.get(id=input.entity_category)
    
    # Call controller with kwargs (provenance is already in the controller)
    result = controller.create_entity(
        entity_category=entity_category,
        ref_id=entity_ref_id,
        action_id=input.action_id,
        action_name=input.action_name,
        action_args=input.action_args,
        supporting_evidence=evidence_list,
    )
    
    # Fetch the created entity for the response
    entity_response = controller.get_entity(id=result.db_id)
    
    return Entity(_value=entity_response)


def recalculate_entity(
    info: Info,
    input: RecalculateEntityInput,
) -> Entity:
    """
    Force recalculation of an entity's derived properties.
    
    This is useful after batch linking operations where
    recalculate was set to False.
    
    Args:
        info: Strawberry Info context
        input: RecalculateEntityInput with graph_id and entity_id
        
    Returns:
        Updated Entity with recalculated properties
    """
    controller = get_controller_for_graph_id(input.graph_id, info)
    
    # Get entity first to find its graph_id and kind
    entity = controller.get_entity(id=input.entity_id)
    
    # Trigger recalculation
    controller._recalculate_entity(
        graph_id=entity.graph_id,
        label=entity.kind,
        schema=controller.definition,
    )
    
    # Return updated entity
    updated_response = controller.get_entity(id=input.entity_id)
    return entity_from_response(updated_response)




