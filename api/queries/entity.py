"""
Entity query resolvers.
"""

from typing import List
from kante.types import Info
import strawberry

from api import types, context, inputs, filters, order, pagination
from core import models
from graph_engine import scalars


def entities(info, graph: strawberry.ID, filters: filters.EntityFilter | None = None, ordering: list[order.EntityOrder] | None = None, pagination: pagination.GraphPaginationInput | None = None) -> List[types.Entity]:
    controller = context.get_controller()

    filter_model = filters.to_pydantic() if filters else None
    ordering_models = [o.to_pydantic() for o in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else None

    graph: models.Graph | None = None

    graph = 

    entity_filters = None
    if filters and filters.matches:
        first_match = filters.matches[0]
        entity_filters = SimpleNamespace(
            key=first_match.key,
            operator=first_match.operator.value,
            value=first_match.value,
        )
    elif filters and filters.search:
        entity_filters = SimpleNamespace(
            key="label",
            operator="CONTAINS",
            value=filters.search,
        )

    entity_pagination = SimpleNamespace(
        limit=pagination.limit if pagination and pagination.limit is not None else 100,
        offset=pagination.offset if pagination and pagination.offset is not None else 0,
    )

    entity_order = None
    if ordering:
        first_order = ordering[0]
        if first_order.property is not None:
            entity_order = SimpleNamespace(
                key=first_order.property.key,
                direction=(first_order.property.direction.value if hasattr(first_order.property.direction, "value") else str(first_order.property.direction)).lower(),
            )

    result = controller.list_entities(
        graph=graph,
        filters=cast(Any, entity_filters),
        pagination=cast(Any, entity_pagination),
        order=cast(Any, entity_order),
    )

    return [types.Entity(_value=entity) for entity in result]


def entity(info: Info, id: scalars.GraphID) -> types.Entity:
    """
    Fetch a single entity by its Global ID.

    Args:
        info: Strawberry Info context
        id: The entity's string ID

    Returns:
        Entity object
    """
    controller = context.get_controller()
    response = controller.get_node_for_composite_id(composite_id=id)
    return types.Entity(_value=response)


def entities_informed_by(info: Info, id: scalars.GraphID) -> List[types.Entity]:
    """
    Fetch all entities that are informed by a given structure.

    Args:
        info: Strawberry Info context
        id: The composite ID of the structure (format: "graph_id:node_id")

    Returns:
        List of Entity objects
    """
    controller = context.get_controller()

    graph = context.extract_graph_id(id)
    identifier = context.extract_node_id(id)

    models.Graph.objects.get(id=graph)  # Validate graph exists

    structures = controller.get_entities_informed_by_structure(graph_id=graph, structure_id=identifier)

    return [types.Entity(_value=r) for r in structures]
