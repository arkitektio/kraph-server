"""
Structure mutation resolvers.
"""

from kante.types import Info
import strawberry

from api import types, inputs, context
from core import models
from graph_engine import scalars


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
    context.validate_graph_access(info, structure_category.graph)

    response = controller.create_structure(
        structure_category=structure_category,
        payload=payload,
        info=info,
    )

    return types.Structure(_value=response)


def ensure_structure(
    info: Info,
    input: inputs.EnsureStructureInput,
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

    graph = models.Graph.objects.get(id=payload.graph)  # Validate graph exists and is accessible

    structure_category = controller.ensure_structure_category_or_raise(graph, payload.identifier, info)  # Validate structure category exists and is accessible

    # TODO: Maybe make this on function?
    response = controller.create_structure(
        structure_category=structure_category,
        payload=payload,
        info=info,
    )

    return types.Structure(_value=response)


def delete_structure(
    info: Info,
    input: inputs.DeleteStructureInput,
) -> scalars.GraphID:
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
    controller.delete_structure(
        structure_id=str(model.id),
        info=info,
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
    structure = controller.archive_structure(
        structure_id=str(model.id),
        info=info,
    )

    return types.Structure(_value=structure)


def update_structure(
    info: Info,
    input: inputs.UpdateStructureInput,
) -> types.Structure:
    """Update an existing structure by its composite ID and return the updated structure."""
    controller = context.get_controller()

    model = input.to_pydantic()
    updated = controller.update_structure(
        structure_id=str(model.id),
        payload=model,
        info=info,
    )

    return types.Structure(_value=updated)


def link_structure_to_entity(
    info: Info,
    input: inputs.LinkStructureInput,
) -> types.Structure:
    """
    Assert that a structure is evidence for an entity.

    This is a pure evidence write: it records the claim that a given ROI (or
    image, or file) justifies a given entity, as an `INFORMS` link under a fresh
    assertion. Which structures support an entity is a statement about the world,
    so it outlives any particular graph projected from it.

    Recording the link also refreshes the entity it now supports, so a structure
    attached after the fact still flows into the derived values.

    Args:
        info: Strawberry Info context
        input: The structure to link and the entity to link it to

    Returns:
        The structure, unchanged apart from now having one more link pointing at it
    """
    controller = context.get_controller()

    graph = context.get_accessible_graph(info, context.extract_graph_id(input.entity_id))
    structure = controller.get_structure_for_identifier(
        graph=graph,
        identifier=input.structure_identifier,
        object=input.structure_object,
        info=info,
    )

    linked = controller.link_structure_to_entity(
        structure_id=str(structure.pk),
        entity_id=input.entity_id,
        info=info,
    )

    return types.Structure(_value=linked)
