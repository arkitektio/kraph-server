"""
Relation mutation resolvers.
"""
from kante.types import Info

from api.types import Relation, RelationCreationResult
from api.inputs import RelationCreationInput
from api.context import get_controller_for_node_id
from graph_engine.input_models import RelationCreationPayload


def _extract_entity_id(composite_id: str) -> str:
    """
    Extract the entity UUID from a composite ID.
    
    Composite IDs are in the format: {graph_id}-{entity_uuid}
    This function returns everything after the first hyphen.
    
    Args:
        composite_id: The composite ID (e.g., "1-abc123-def456-...")
        
    Returns:
        The entity UUID part (e.g., "abc123-def456-...")
    """
    parts = composite_id.split("-", 1)
    if len(parts) == 2:
        return parts[1]
    return composite_id


def create_relation(
    info: Info,
    input: RelationCreationInput,
) -> RelationCreationResult:
    """
    Create a new relation between two entities with optional supporting evidence.
    
    Relations are edges between entities that can be backed by evidence
    (e.g., ROI overlaps that prove a synapse connection). Properties on
    the relation are automatically derived from the evidence according
    to the graph schema's materialization rules.
    
    Args:
        info: Strawberry Info context
        input: RelationCreationInput (pydantic-validated)
        
    Returns:
        RelationCreationResult with the created relation
    """
    # Convert strawberry-pydantic input to pydantic model
    payload = input.to_pydantic()
    
    # Get controller from source entity's graph
    controller = get_controller_for_node_id(payload.source_id, info)
    
    # Extract the actual entity IDs from the composite IDs
    # The controller expects just the entity UUID, not the composite ID
    source_entity_id = _extract_entity_id(payload.source_id)
    target_entity_id = _extract_entity_id(payload.target_id)
    
    # Create a new payload with the extracted entity IDs
    controller_payload = RelationCreationPayload(
        ref_id=payload.ref_id,
        kind=payload.kind,
        source_id=source_entity_id,
        target_id=target_entity_id,
        supporting_evidence=payload.supporting_evidence,
        provenance=payload.provenance,
    )
    
    result = controller.create_relation(controller_payload)
    
    # Fetch the created relation edge for the response
    relation_edge = controller.get_relation_by_id(result.graph_id)
    relation = Relation(_value=relation_edge) if relation_edge else None
    
    return RelationCreationResult(
        ref_id=result.ref_id,
        db_id=result.db_id,
        graph_id=str(result.graph_id),
        status=result.status,
        relation=relation,
    )
