"""
Relation mutation resolvers.
"""
from kante.types import Info

from api.types import Relation, RelationCreationResult
from api.inputs import RelationCreationInput
from api.context import get_controller_from_context


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
    controller = get_controller_from_context(info)
    
    # Convert strawberry-pydantic input to pydantic model
    payload = input.to_pydantic()
    
    result = controller.create_relation(payload)
    
    # Fetch the created relation edge for the response
    relation_edge = controller.get_relation_by_id(result.graph_id)
    relation = Relation(_value=relation_edge) if relation_edge else None
    
    return RelationCreationResult(
        ref_id=result.ref_id,
        db_id=result.db_id,
        graph_id=result.graph_id,
        status=result.status,
        relation=relation,
    )
