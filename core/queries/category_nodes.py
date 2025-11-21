from typing import Union, Optional
from core import models, types, enums, filters as f, pagination as p, age, inputs
import strawberry
from kante.types import Info
from core.renderers.graph.render import render_graph_query as render_graph_query_raw


def entity_nodes(
    info: Info,
    id: strawberry.ID,
    filters: f.CategoryNodesFilter | None = None,
    pagination: inputs.GraphQueryPagination | None = None,
    order: f.CategoryNodesOrder | None = None,
) -> list[types.Entity]:
    node_category = models.NodeCategory.objects.get(id=id)

    all_items = age.get_category_nodes(node_category, filters=filters, order=order, pagination=pagination)

    return [types.Entity(_value=i) for i in all_items]


def entity_category_stats(
    info: Info,
    id: strawberry.ID,
    filters: f.CategoryNodesFilter | None = None,
    pagination: inputs.GraphQueryPagination | None = None,
    order: f.CategoryNodesOrder | None = None,
) -> types.EntityCategoryStats:
    node_category = models.NodeCategory.objects.get(id=id)

    stats = age.get_entity_category_stats(node_category, filters=filters, order=order, pagination=pagination)

    return types.EntityCategoryStats(**stats)
