"""
Entity query resolvers.
"""

from typing import List, Any, cast
from types import SimpleNamespace
from kante.types import Info
import strawberry

from api import types, context, inputs, filters, order, pagination
from core import models
from graph_engine import scalars


def entities(info, graph: strawberry.ID, filters: filters.EntityFilter | None = None, ordering: list[order.EntityOrder] | None = None, pagination: pagination.EntityPaginationInput | None = None) -> List[types.Entity]:
    controller = context.get_controller()

    filter_model = filters.to_pydantic() if filters else None
    ordering_models = [o.to_pydantic() for o in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else None

    graph_model = models.Graph.objects.get(id=graph)  # Validate graph exists
    graph_model.validate_accessible(info.context.request.member)

    result = controller.list_entities(
        graph=graph_model,
        filters=filter_model,
        pagination=pagination_model,
        ordering=ordering_models,
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
