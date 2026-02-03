"""
Structure mutation resolvers.
"""
from kante.types import Info

from api.types import Structure, LinkStructureResult, structure_from_response, entity_from_response
from api.inputs import StructureCreationInputType, LinkStructureInputType
from api.context import get_controller_from_context


def create_structure(
    info: Info,
    input: StructureCreationInputType,
) -> Structure:
    """
    Create a new structure (or return existing if already exists).
    
    Structures are idempotent - creating the same structure twice
    returns the existing one.
    
    Args:
        info: Strawberry Info context
        input: StructureCreationInputType (pydantic-validated)
        
    Returns:
        Structure object
    """
    controller = get_controller_from_context(info)
    
    # Convert strawberry-pydantic input to pydantic model
    payload = input.to_pydantic()
    
    response = controller.create_structure(
        identifier=payload.identifier,
        object=payload.object,
    )
    
    return structure_from_response(response)


def link_structure_to_entity(
    info: Info,
    input: LinkStructureInputType,
) -> LinkStructureResult:
    """
    Link an existing structure to an existing entity.
    
    This creates an INFORMS relationship, allowing the structure's
    measurements to contribute to the entity's derived properties.
    
    By default, entity properties are recalculated after linking.
    Set recalculate=False for batch operations.
    
    Args:
        info: Strawberry Info context
        input: LinkStructureInputType
        
    Returns:
        LinkStructureResult with updated entity and structure
    """
    controller = get_controller_from_context(info)
    
    entity_response = controller.link_structure_to_entity(
        structure_identifier=input.structure_identifier,
        structure_object=input.structure_object,
        entity_id=input.entity_id,
        recalculate=input.recalculate if input.recalculate is not None else True,
    )
    
    structure_response = controller.get_structure(
        identifier=input.structure_identifier,
        object=input.structure_object,
    )
    
    return LinkStructureResult(
        success=True,
        entity=entity_from_response(entity_response),
        structure=structure_from_response(structure_response),
    )
