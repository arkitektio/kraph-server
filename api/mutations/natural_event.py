"""
Natural event mutation resolvers.
"""

from kante.types import Info
import time

from api import types, inputs, context
from core import models
from graph_engine import scalars


def _archive_natural_event_by_local_id(controller, graph, local_id: scalars.LocalID, info: Info) -> None:
    assertion_id = controller._create_provenance_node(graph, controller._provenance_from_info(info))
    archived_at = int(time.time() * 1000)

    controller.engine.execute(
        graph,
        """
        MATCH (a:Assertion) WHERE id(a) = $aid
        MATCH (e) WHERE id(e) = $eid
        CREATE (lc:LifeCycleAssertion {status: $status, archived_at: $archived_at, timestamp: $timestamp})
        CREATE (a)-[:ASSERTED]->(lc)
        CREATE (lc)-[:INFORMS]->(e)
        RETURN id(lc) as lifecycle_id
        """,
        {
            "aid": assertion_id,
            "eid": local_id,
            "status": "archived",
            "archived_at": archived_at,
            "timestamp": archived_at,
        },
    )


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
        info=info,
    )

    return types.NaturalEvent(_value=response)


def delete_natural_event(
    info: Info,
    input: inputs.DeleteNaturalEventInput,
) -> scalars.GraphID:
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

    graph = context.get_accessible_graph(info, graph_id)

    controller.delete_entity(graph, local_id=local_id)

    return model.id


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

    graph = context.get_accessible_graph(info, graph_id)

    _archive_natural_event_by_local_id(controller, graph, local_id, info)

    archived = controller.get_node_by_local_id(graph, local_id=local_id, info=info)

    return types.NaturalEvent(_value=archived)


def update_natural_event(
    info: Info,
    input: inputs.UpdateNaturalEventInput,
) -> types.NaturalEvent:
    """
    Update a natural event by archiving the current event and creating a new one in the same category.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)
    existing = controller.get_node_by_local_id(graph, local_id=local_id, info=info)

    category = models.NaturalEventCategory.objects.get(id=existing.category_id)

    _archive_natural_event_by_local_id(controller, graph, local_id, info)

    updated = controller.create_natural_event(
        category=category,
        payload=model,
        info=info,
    )

    return types.NaturalEvent(_value=updated)
