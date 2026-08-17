"""Natural event query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, filters, order, pagination, types
from api.queries import _nodes
from core import models
from evidence import models as evidence_models
from graph_engine import input_models, scalars


def natural_event(info: Info, id: scalars.GraphID, graph: strawberry.ID) -> types.NaturalEvent:
    """One natural event, as the named view holds it — see `node(id:, graph:)`.

    The id is the node's own uuid — no graph to take off the front of it — but
    the *shape* of the answer is a drawing, so the view supplying it is named.
    """
    controller = context.get_controller()
    graph_model = context.get_accessible_graph(info, graph)
    instance = controller._resolve_instance(str(id), info)
    if instance.kind != evidence_models.Instance.Kind.NATURAL_EVENT:
        raise ValueError(f"Node '{id}' is a {instance.kind}, not a natural event. Fetch it with the query matching its kind, or `node(id:, graph:)` for any kind.")
    return types.NaturalEvent(_value=_nodes.one_in_graph(controller, graph_model, instance))


def natural_events(
    info: Info,
    natural_event_category_id: strawberry.ID,
    filters: filters.NaturalEventFilter | None = None,
    ordering: list[order.NaturalEventOrder] | None = None,
    pagination: pagination.NaturalEventPaginationInput | None = None,
) -> List[types.NaturalEvent]:
    """Every natural event this category draws, from the claims.

    The same change as `protocol_events`, for the same reason: the list was a list of
    vertices, so it answered what the view had drawn rather than what its rule admits.
    See `api/queries/_nodes.py`.
    """
    controller = context.get_controller()

    category = models.NaturalEventCategory.objects.filter(id=natural_event_category_id).first()
    if category is None:
        raise ValueError(f"Natural event category {natural_event_category_id} not found")

    graph = context.get_accessible_graph(info, str(category.graph.age_name))

    filter_model = filters.to_pydantic() if filters else input_models.NaturalEventFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.NaturalEventPagination()

    rows = _nodes.narrow(_nodes.rows_for_category(category), filter_model, ordering_models, pagination_model)

    return [types.NaturalEvent(_value=node) for node in _nodes.retrieved_in(controller, graph, rows)]
