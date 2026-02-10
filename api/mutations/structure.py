"""
Structure mutation resolvers.
"""

from kante.types import Info
import strawberry

from api import types, inputs, context
from core import models


def create_structure(
    info: Info,
    input: inputs.CreateStructureInput,
) -> types.Structure:
    """
    Create a new structure (or return existing if already exists).

    Structures are idempotent - creating the same structure twice
    returns the existing one.

    Args:
        info: Strawberry Info context
        input: inputs.CreateStructureInput (pydantic-validated)

    Returns:
        types.Structure object
    """
    # Convert strawberry-pydantic input to pydantic model
    payload = input.to_pydantic()

    controller = context.get_controller()

    structure_category = models.StructureCategory.objects.get(id=payload.category)  # Validate structure category exists

    response = controller.create_structure(
        structure_category=structure_category,
        payload=payload,
    )

    return types.Structure(_value=response)


def delete_structure(
    info: Info,
    input: inputs.DeleteStructureInput,
) -> strawberry.ID:
    """
    Delete a structure by its composite ID. Only the owner of the graph or an admin can delete a structure.

    Args:
        info: Strawberry Info context
        input: Composite ID of the structure to delete (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the deleted structure
    """
    controller = context.get_controller()

    model = input.to_pydantic()  # Validate input with Pydantic models
    # Extract graph ID and local ID from composite ID
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    controller.delete_structure(
        graph,
        structure_id=local_id,
        provenance=context.get_provenance_from_context(info),
    )

    return model.id


def archive_structure(
    info: Info,
    input: inputs.ArchiveStructureInput,
) -> types.Structure:
    """
    Archive (soft delete) a structure by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the structure to archive (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the archived structure
    """
    controller = context.get_controller()

    model = input.to_pydantic()  # Validate input with Pydantic models
    # Extract graph ID and local ID from composite ID
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    structure = controller.archive_structure(
        graph,
        structure_id=local_id,
        provenance=context.get_provenance_from_context(info),
    )

    return types.Structure(_value=structure)


def link_structure_to_entity(
    info: Info,
    input: inputs.LinkStructureInput,
) -> types.Informs:
    """
    Link an existing structure to an existing entity.

    This creates an INFORMS relationship, allowing the structure's
    measurements to contribute to the entity's derived properties.

    By default, entity properties are recalculated after linking.
    Set recalculate=False for batch operations.

    Args:
        info: Strawberry Info context
        input: LinkStructureInput

    Returns:
        types.Informs object representing the new relationship
    """

    controller = context.get_controller()

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
