"""
Protocol event mutation resolvers.
"""

from kante.types import Info

from api import context, inputs, types
from core import models
from evidence import writer
from graph_engine import scalars


def _archive_protocol_event_by_local_id(controller, graph, local_id: scalars.LocalID, info: Info) -> None:
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


def create_protocol_event(
    info: Info,
    input: inputs.CreateProtocolEventInput,
) -> types.ProtocolEvent:
    controller = context.get_controller()

    protocol_event = input.to_pydantic()

    category = models.ProtocolEventCategory.objects.get(id=protocol_event.event_category)

    response = controller.create_natural_event(
        category=category,
        payload=protocol_event,
        info=info,
    )

    return types.ProtocolEvent(_value=response)


def delete_protocol_event(
    info: Info,
    input: inputs.DeleteProtocolEventInput,
) -> scalars.GraphID:
    controller = context.get_controller()

    model = input.to_pydantic()
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)

    controller.delete_entity(graph, local_id=local_id)

    return model.id


def archive_protocol_event(
    info: Info,
    input: inputs.ArchiveProtocolEventInput,
) -> types.ProtocolEvent:
    controller = context.get_controller()

    model = input.to_pydantic()
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)

    _archive_protocol_event_by_local_id(controller, graph, local_id, info)

    archived = controller.get_node_by_local_id(graph, local_id=local_id, info=info)

    return types.ProtocolEvent(_value=archived)


def update_protocol_event(
    info: Info,
    input: inputs.UpdateProtocolEventInput,
) -> types.ProtocolEvent:
    controller = context.get_controller()

    model = input.to_pydantic()
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)
    existing = controller.get_node_by_local_id(graph, local_id=local_id, info=info)

    category = models.ProtocolEventCategory.objects.get(id=existing.category_id)

    _archive_protocol_event_by_local_id(controller, graph, local_id, info)

    updated = controller.create_natural_event(
        category=category,
        payload=model,
        info=info,
    )

    return types.ProtocolEvent(_value=updated)
