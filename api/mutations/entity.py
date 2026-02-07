"""
Entity mutation resolvers.
"""
from kante.types import Info

from api.types import Entity
from api.inputs import EntityCreationInput, RecalculateEntityInput
from api.context import get_controller, extract_graph_id, extract_node_id
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
    
    
    
    input_model = input.to_pydantic()  # Validate input with Pydantic models
    
    entity_category = models.EntityCategory.objects.get(id=input_model.entity_category)  # Validate graph exists
    
    # Get controller for the specified graph (includes provenance from context)
    controller = get_controller()
    
            
    
    ref_id = str(uuid.uuid4())  # Generate a unique reference ID for the entity
    # Call controller with kwargs (provenance is already in the controller)
    result = controller.create_entity(
        entity_category=entity_category,
        ref_id=ref_id,
        supporting_evidence=input_model.supporting_evidence,
    )
    
    # Fetch the created entity for the response
    entity_response = controller.get_entity(id=result.db_id, entity_category=entity_category)
    
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
    controller = get_controller()
    
    graph_id = extract_graph_id(input.entity_id)
    node_id = extract_node_id(input.entity_id)
    
    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists
    
    # Get entity first to find its  and kind
    entity = controller.get_node(graph, entity_id=node_id)
    
    
    return Entity(_value=entity)




