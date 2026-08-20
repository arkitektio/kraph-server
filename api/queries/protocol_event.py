"""Protocol event query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, filters, order, pagination, types
from api.queries import _nodes
from core import models
from evidence import models as evidence_models
from graph_engine import input_models


def protocol_event(info: Info, id: strawberry.ID, graph: strawberry.ID) -> types.ProtocolEvent:
    """One protocol event, as the named view holds it — see `node(id:, graph:)`.

    The id is the node's own uuid — no graph to take off the front of it — but
    the *shape* of the answer is a drawing, so the view supplying it is named.
    """
    controller = context.get_controller()
    graph_model = context.get_accessible_graph(info, graph)
    instance = controller._resolve_instance(str(id), info)
    if instance.kind != evidence_models.Instance.Kind.PROTOCOL_EVENT:
        raise ValueError(f"Node '{id}' is a {instance.kind}, not a protocol event. Fetch it with the query matching its kind, or `node(id:, graph:)` for any kind.")
    return types.ProtocolEvent(_value=_nodes.one_in_graph(controller, graph_model, instance))


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

    # Organization first, then the view's access rules — see `api/queries/entity.py`.
    context.assert_can_access_organization(info, category.graph.organization)
    graph = context.validate_graph_access(info, category.graph)

    filter_model = filters.to_pydantic() if filters else input_models.ProtocolEventFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.ProtocolEventPagination()

    rows = _nodes.narrow(_nodes.rows_for_category(category), filter_model, ordering_models, pagination_model)

    # Dispatched on the claim's kind — see `api/queries/natural_event.py`.
    return [types.cast_node_to_graphql_type(node) for node in _nodes.retrieved_in(controller, graph, rows)]  # type: ignore[return-value]
