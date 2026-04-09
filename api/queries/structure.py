"""
Structure query resolvers.
"""

from typing import Optional, List
from kante.types import Info
import strawberry

from api import types, context, filters, order, pagination
from core import models
from graph_engine import scalars
from graph_engine import input_models


def structure_by_identifier(
    info: Info,
    graph: strawberry.ID,
    identifier: scalars.StructureIdentifier,
    object: scalars.StructureObject,
) -> types.Structure:
    """
    Fetch a specific structure by its identifier and object ID.

    Args:
        info: Strawberry Info context
        graph: Graph ID
        identifier: Structure identifier (e.g. '@mikro/roi')
        object: Structure object ID

    Returns:
        Structure object or None if not found
    """
    controller = context.get_controller()
    graph_model = context.get_accessible_graph(info, str(graph))

    response = controller.get_structure(
        graph=graph_model,
        identifier=identifier,
        object=object,
        info=info,
    )

    return types.Structure(_value=response)


def structure(
    info: Info,
    id: scalars.GraphID,
) -> types.Structure:
    """
    Fetch a specific structure by composite graph ID.

    Args:
        info: Strawberry Info context
        id: Composite graph id (format: "graph_id:node_id")

    Returns:
        Structure object or None if not found
    """
    controller = context.get_controller()

    graph_id = context.extract_graph_id(id)
    local_id = context.extract_node_id(id)

    graph = context.get_accessible_graph(info, graph_id)
    response = controller.get_node(graph=graph, local_id=local_id, info=info)

    return types.Structure(_value=response)


def structures(
    info: Info,
    structure_category_id: strawberry.ID,
    filters: filters.StructureFilter | None = None,
    ordering: list[order.StructureOrder] | None = None,
    pagination: pagination.StructurePaginationInput | None = None,
) -> List[types.Structure]:
    """Fetch structures for a given structure category with optional filters, ordering, and pagination."""
    controller = context.get_controller()

    structure_category = models.StructureCategory.objects.filter(id=structure_category_id).first()
    if structure_category is None:
        raise ValueError(f"Structure category {structure_category_id} not found")

    filter_model = filters.to_pydantic() if filters else input_models.StructureFilters()
    filter_model.category = structure_category.identifier
    ordering_models = [order.to_pydantic() for order in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.StructurePagination()

    result = controller.list_structures(
        graph=structure_category.graph,
        filters=filter_model,
        pagination=pagination_model,
        ordering=ordering_models,
        info=info,
    )

    return [types.Structure(_value=structure) for structure in result]


def informing_structures(
    info: Info,
    entity_id: str,
) -> List[types.Structure]:
    """
    Fetch all structures that inform a given entity.

    Args:
        info: Strawberry Info context
        entity_id: The entity's string ID

    Returns:
        List of Structure objects
    """
    controller = context.get_controller()

    graph_id = context.extract_graph_id(entity_id)
    context.extract_node_id(entity_id)

    graph = context.get_accessible_graph(info, graph_id)

    responses = controller.get_informing_structures(graph, entity_id=entity_id, info=info)
    return [types.Structure(_value=r) for r in responses]
