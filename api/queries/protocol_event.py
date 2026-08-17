"""Protocol event query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, filters, order, pagination, types
from api.queries import _nodes
from core import models
from graph_engine import input_models, scalars


def protocol_event(info: Info, id: scalars.GraphID) -> types.ProtocolEvent:
    """Fetch a specific protocol event by its uuid."""
    controller = context.get_controller()

    # The id is the node's own uuid, so there is no graph to take off the front
    # of it: the `Instance` row says what was claimed, and `drawings` says which views
    # draw it.
    response = controller.get_node(node_id=id, info=info)
    if response is None:
        raise ValueError(f"Protocol event with ID {id} not found")

    return types.ProtocolEvent(_value=response)


def protocol_events(
    info: Info,
    protocol_event_category_id: strawberry.ID,
    filters: filters.ProtocolEventFilter | None = None,
    ordering: list[order.ProtocolEventOrder] | None = None,
    pagination: pagination.ProtocolEventPaginationInput | None = None,
) -> List[types.ProtocolEvent]:
    """Every protocol event this category draws, from the claims.

    This was ninety lines of hand-built Cypher matching `n.category_id = $id` in
    `category.graph`, which answered "what has this view drawn" rather than "what
    does this view's rule admit" — an event claimed under the category's word but not
    yet projected was missing, and the answer moved when the projection was rebuilt.
    Membership comes from the claims now; see `api/queries/_nodes.py`.
    """
    controller = context.get_controller()

    category = models.ProtocolEventCategory.objects.filter(id=protocol_event_category_id).first()
    if category is None:
        raise ValueError(f"Protocol event category {protocol_event_category_id} not found")

    graph = context.get_accessible_graph(info, str(category.graph.age_name))

    filter_model = filters.to_pydantic() if filters else input_models.ProtocolEventFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.ProtocolEventPagination()

    rows = _nodes.narrow(_nodes.rows_for_category(category), filter_model, ordering_models, pagination_model)

    return [types.ProtocolEvent(_value=node) for node in _nodes.retrieved_in(controller, graph, rows)]
