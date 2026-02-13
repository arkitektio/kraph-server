"""
Measurement mutation resolvers.
"""

from kante.types import Info
import strawberry

from api import types, inputs, context
from core import models


def create_natural_event(
    info: Info,
    input: inputs.CreateNaturalEventInput,
) -> types.NaturalEvent:
    """
    Add a measurement to an existing structure.

    If the structure doesn't exist, it will be created automatically.

    Args:
        info: Strawberry Info context
        input: CreateNaturalEventInput

    Returns:
        Created Measurement object
    """
    controller = context.get_controller()

    # Convert strawberry-pydantic inputs to pydantic models
    natural_event = input.to_pydantic()

    category = models.NaturalEventCategory.objects.get(id=natural_event.event_category)  # Validate graph exists

    response = controller.create_natural_event(
        category=category,
        payload=natural_event,
    )

    return types.NaturalEvent(_value=response)


def delete_natural_event(
    info: Info,
    input: inputs.DeleteNaturalEventInput,
) -> strawberry.ID:
    """
    Delete a natural event by its composite ID.
    Only the owner of the graph or an admin can delete a natural event.

    Args:
        info: Strawberry Info context
        input: Composite ID of the natural event to delete (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the deleted natural event
    """
    controller = context.get_controller()

    model = input.to_pydantic()  # Validate input with Pydantic models
    # Extract graph ID and local ID from composite ID
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    context.get_accessible_graph(info, graph_id)

    response = controller.delete_natural_event(graph_id=graph_id, local_id=local_id)

    return strawberry.ID(response)


def archive_natural_event(
    info: Info,
    input: inputs.ArchiveNaturalEventInput,
) -> types.NaturalEvent:
    """
    Archive (soft delete) a natural event by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the natural event to archive (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the archived natural event
    """
    controller = context.get_controller()

    model = input.to_pydantic()  # Validate input with Pydantic models
    # Extract graph ID and local ID from composite ID
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    context.get_accessible_graph(info, graph_id)

    response = controller.archive_natural_event(graph_id=graph_id, local_id=local_id)

    return types.NaturalEvent(_value=response)
