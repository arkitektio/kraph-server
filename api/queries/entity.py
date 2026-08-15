"""
Entity query resolvers.
"""

from typing import List
from kante.types import Info
import strawberry

from api import types, context, inputs, filters, order, pagination
from core import models
from graph_engine import scalars
from graph_engine import input_models


def _coerce_filter_value(value):
    if not isinstance(value, str):
        return value

    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"

    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def entities(
    info: Info,
    entity_category_id: strawberry.ID,
    filters: filters.EntityFilter | None = None,
    ordering: list[order.EntityOrder] | None = None,
    pagination: pagination.EntityPaginationInput | None = None,
) -> List[types.Entity]:
    controller = context.get_controller()

    entity_category = models.EntityCategory.objects.filter(id=entity_category_id).first()
    if entity_category is None:
        raise ValueError(f"Entity category {entity_category_id} not found")

    filter_model = filters.to_pydantic() if filters else input_models.EntityFilters()
    filter_model.category = entity_category.age_name
    ordering_models = [order.to_pydantic() for order in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.EntityPagination()

    result = controller.list_entities(
        graph=entity_category.graph,
        filters=filter_model,
        pagination=pagination_model,
        ordering=ordering_models,
        info=info,
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
    response = controller.get_node_for_composite_id(composite_id=id, info=info)
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

    # A structure id is a bare evidence primary key and always has been — there
    # was never a graph in it to extract, and doing so split the uuid on its
    # first hyphen and looked up a graph called "a3f2c1d4".
    organization = context.get_active_organization(info)
    structure = controller._resolve_structure(str(id), info)

    entities = []
    for graph in models.Graph.objects.filter(organization=organization):
        entities.extend(controller.list_entities_informed_by_structure(graph=graph, structure_id=structure.pk, info=info))

    return [types.Entity(_value=r) for r in entities]
