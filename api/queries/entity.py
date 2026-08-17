"""Entity query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, filters, order, pagination, types
from api.queries import _nodes
from core import models
from graph_engine import input_models, scalars


def entities(
    info: Info,
    entity_category_id: strawberry.ID,
    filters: filters.EntityFilter | None = None,
    ordering: list[order.EntityOrder] | None = None,
    pagination: pagination.EntityPaginationInput | None = None,
) -> List[types.Entity]:
    """Every entity this category draws, from the claims.

    Read from `evidence.Node`, not from Apache AGE: a node this category's rule
    admits is in the list whether or not the view has drawn it yet, and the ids are
    the claims' own — see `api/queries/_nodes.py`.

    **Authorized, which it was not.** This fetched the category by bare primary key
    and relied on `GraphController._ensure_query_access`, which was a stub that
    returned unconditionally — so any member of any tenant could list another
    organization's entities by guessing an integer. A category belongs to one graph
    and its rule is that view's, so the graph is the boundary that applies, exactly
    as for the sibling event lists.
    """
    controller = context.get_controller()

    entity_category = models.EntityCategory.objects.filter(id=entity_category_id).first()
    if entity_category is None:
        raise ValueError(f"Entity category {entity_category_id} not found")

    graph = context.get_accessible_graph(info, str(entity_category.graph.age_name))

    filter_model = filters.to_pydantic() if filters else input_models.EntityFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.EntityPagination()

    rows = _nodes.narrow(_nodes.rows_for_category(entity_category), filter_model, ordering_models, pagination_model)

    return [types.Entity(_value=node) for node in _nodes.retrieved_in(controller, graph, rows)]


def entity(info: Info, id: scalars.GraphID) -> types.Entity:
    """
    Fetch a single entity by its id.

    Args:
        info: Strawberry Info context
        id: The entity's uuid

    Returns:
        Entity object
    """
    controller = context.get_controller()
    response = controller.get_node(node_id=id, info=info)
    return types.Entity(_value=response)


# `entities_informed_by` used to sit here, and it was **in no schema** — exported from
# `api/queries/__init__.py`, listed in its `__all__`, and named by no field on `Query`,
# so nothing could ever call it. It was also the last place that fanned a claim query
# out over graphs: it looped every `Graph` in the organization asking each what it drew,
# which listed a node twice when two views declared its word and cost a Cypher
# round-trip per view, to answer a question `INFORMS` does not ask — nothing about that
# claim names a graph. The direction that *is* wired, `informingStructures`, has never
# needed a graph either. Deleted rather than fixed and left unreachable.
