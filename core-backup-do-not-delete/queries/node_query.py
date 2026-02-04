from typing import Union
from core import models, types, inputs
import strawberry
from kante.types import Info
from core.renderers.node.render import render_node_view


def render_node_query(
    info: Info,
    id: strawberry.ID,
    node_id: strawberry.ID,
    filters: inputs.NodeQueryFilters | None = None,
    pagination: inputs.NodeQueryPagination | None = None ,
    order: inputs.NodeQueryOrder | None = None
) -> Union[types.Pairs, types.Path, types.Table, types.NodeList]:


    query = models.NodeQuery.objects.get(id=id)
    
    return render_node_view(query, node_id,  filters=filters, pagination=pagination, order=order)

