"""
Natural event mutation resolvers.
"""

from kante.types import Info

from api import types, inputs, context
from core import models
from evidence import writer
from graph_engine import scalars


def _archive_natural_event_by_local_id(controller, graph, local_id: scalars.LocalID, info: Info) -> None:
    # The retraction is an assertion about instance data, so it goes to the
    # evidence lifecycle log. The previous version created a LifeCycleAssertion
    # vertex hanging off an `(a:Assertion)` match that no longer resolves after
    # M1 — the CREATE simply never fired and the archive was silently dropped.
    assertion = controller._create_assertion(graph.organization, controller._provenance_from_info(info))

    writer.archive_ref(
        graph.organization,
        target_type="event",
        target_id=f"{graph.age_name}:{local_id}",
        assertion=assertion,
    )

    controller.engine.execute(
        graph,
        """
        MATCH (e) WHERE id(e) = $eid
        SET e.__lifecycle_state = $status
        """,
        {"eid": local_id, "status": "archived"},
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
