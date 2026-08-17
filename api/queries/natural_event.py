"""Natural event query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, filters, order, pagination, types
from api.queries import _nodes
from core import models
from graph_engine import input_models, scalars


def natural_event(info: Info, id: scalars.GraphID) -> types.NaturalEvent:
    """Fetch a specific natural event by its uuid."""
    controller = context.get_controller()

    # The id is the node's own uuid, so there is no graph to take off the front
    # of it: the `Instance` row says what was claimed, and `drawings` says which views
    # draw it.
    response = controller.get_node(node_id=id, info=info)
    if response is None:
        raise ValueError(f"Natural event with ID {id} not found")

    return types.NaturalEvent(_value=response)


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
