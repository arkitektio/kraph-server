"""
Entity mutation resolvers.
"""
import strawberry
from kante.types import Info

from api.types import Entity, EntityCreationResult, entity_from_response
from api.inputs import EntityCreationInput, RecalculateEntityInput
from api.context import get_controller_for_graph_id
from graph_engine.controller import GraphController
from graph_engine.engine.age_engine import AgeEngine
from graph_engine.engine.protocol import SimpleGraph
from core.models import Graph



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
        input: EntityCreationInput with graph_id, kind, and evidence
        
    Returns:
        EntityCreationResult with the created entity
    """
    import uuid
    
    # Get controller for the specified graph (includes provenance from context)
    controller = get_controller_for_graph_id(input.graph_id, info)
    
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
    
    # Call controller with kwargs (provenance is already in the controller)
    result = controller.create_entity(
        kind=input.kind,
        ref_id=entity_ref_id,
        action_id=input.action_id,
        action_name=input.action_name,
        action_args=input.action_args,
        supporting_evidence=evidence_list,
    )
    
    # Fetch the created entity for the response
    entity_response = controller.get_entity(id=result.db_id)
    entity = entity_from_response(entity_response)
    
    # Create composite db_id in format {graph_id}-{entity_uuid}
    # This allows get_controller_for_node_id to extract the graph ID
    composite_db_id = f"{input.graph_id}-{result.db_id}"
    
    return EntityCreationResult(
        ref_id=result.ref_id,
        db_id=composite_db_id,
        graph_id=str(result.graph_id),
        status=result.status,
        entity=entity,
    )


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




