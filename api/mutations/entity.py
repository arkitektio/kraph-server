"""
Entity mutation resolvers.
"""

from kante.types import Info
from api import inputs, types, context
from core import models


def create_entity(
    info: Info,
    input: inputs.CreateEntityInput,
) -> types.Entity:
    """
    Create a new entity with optional supporting evidence structures.

    Properties are automatically derived from the evidence according to
    the graph schema rules.

    Args:
        info: Strawberry Info context
        input: CreateEntityInput         with graph_id, kind, and evidence

    Returns:
        EntityCreationResult with the created entity
    """
    import uuid

    input_model = input.to_pydantic()  # Validate input with Pydantic models

    entity_category = models.EntityCategory.objects.get(id=input_model.entity_category)  # Validate graph exists

    # Get controller for the specified graph (includes provenance from context)
    controller = context.get_controller()

    # Call controller with kwargs (provenance is already in the controller)
    result = controller.create_entity(
        entity_category=entity_category,
        payload=input_model,
        context=context.get_provenance_from_context(info),
    )

    return types.Entity(_value=result)


def delete_entity(
    info: Info,
    input: inputs.DeleteEntityInput,
) -> types.Entity:
    """
    Delete an entity by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the entity to delete (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the deleted entity
    """
    controller = context.get_controller()
    model = input.to_pydantic()  # Validate input with Pydantic models

    graph_id = context.extract_graph_id(model.id)
    node_id = context.extract_node_id(model.id)

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    controller.delete_entity(graph, entity_id=node_id)

    return input


def archive_entity(
    info: Info,
    input: inputs.ArchiveEntityInput,
) -> types.Entity:
    """
    Archive (soft delete) an entity by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the entity to archive (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the archived entity
    """
    controller = context.get_controller()

    graph_id = context.extract_graph_id(input.id)
    node_id = context.extract_node_id(input.id)

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    controller.archive_entity(graph, entity_id=node_id)

    return input


def recalculate_entity(
    info: Info,
    input: inputs.RecalculateEntityInput,
) -> types.Entity:
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
    controller = context.get_controller()

    graph_id = context.extract_graph_id(input.entity_id)
    node_id = context.extract_node_id(input.entity_id)

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    # Get entity first to find its  and kind
    entity = controller.get_node(graph, entity_id=node_id)

    return types.Entity(_value=entity)
