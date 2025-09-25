from typing import Union, Optional
from core import models, types, enums, filters as f, pagination as p, age, inputs
import strawberry
from kante.types import Info
from core.renderers.graph.render import render_graph_query as render_graph_query_raw


def render_graph_query(
    info: Info,
    id: strawberry.ID,
    filters: inputs.GraphQueryFilters | None = None,
    pagination: inputs.GraphQueryPagination | None = None,
    order: inputs.GraphQueryOrder | None = None,
) -> Union[types.Pairs, types.Path, types.Table, types.NodeList]:
    query = models.GraphQuery.objects.get(id=id)

    return render_graph_query_raw(info, query, filters=filters, pagination=pagination, order=order)
