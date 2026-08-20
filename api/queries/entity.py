"""Entity query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, filters, order, pagination, types
from api.queries import _nodes
from core import models
from evidence import models as evidence_models
from graph_engine import input_models


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

    # Authorized against the organization the category belongs to, like every other
    # category-scoped list (`api/queries/relation.py`), then the view's own access
    # rules. This used to round-trip `category.graph.age_name` through the `graph:`
    # resolver; the handle is internal now and resolves nothing.
    context.assert_can_access_organization(info, entity_category.graph.organization)
    graph = context.validate_graph_access(info, entity_category.graph)

    filter_model = filters.to_pydantic() if filters else input_models.EntityFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.EntityPagination()

    rows = _nodes.narrow(_nodes.rows_for_category(entity_category), filter_model, ordering_models, pagination_model)

    # Dispatched on the claim's kind — see `api/queries/natural_event.py`.
    return [types.cast_node_to_graphql_type(node) for node in _nodes.retrieved_in(controller, graph, rows)]  # type: ignore[return-value]


def entity(info: Info, id: strawberry.ID, graph: strawberry.ID) -> types.Entity:
    """One entity, as the named view holds it — see `node(id:, graph:)`.

    Guards the kind, where it used to wrap whatever row the id named into
    `Entity` blindly — an event's uuid came back wearing the wrong type.
    """
    controller = context.get_controller()
    graph_model = context.get_accessible_graph(info, graph)
    instance = controller._resolve_instance(str(id), info)
    if instance.kind != evidence_models.Instance.Kind.ENTITY:
        raise ValueError(f"Node '{id}' is a {instance.kind}, not an entity. Fetch it with the query matching its kind, or `node(id:, graph:)` for any kind.")
    return types.Entity(_value=_nodes.one_in_graph(controller, graph_model, instance))


# `entities_informed_by` used to sit here, and it was **in no schema** — exported from
# `api/queries/__init__.py`, listed in its `__all__`, and named by no field on `Query`,
# so nothing could ever call it. It was also the last place that fanned a claim query
# out over graphs: it looped every `Graph` in the organization asking each what it drew,
# which listed a node twice when two views declared its word and cost a Cypher
# round-trip per view, to answer a question `INFORMS` does not ask — nothing about that
# claim names a graph. The direction that *is* wired, `informingStructures`, has never
# needed a graph either. Deleted rather than fixed and left unreachable.
