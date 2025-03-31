from typing import Union
from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from core.renderers.node.render import render_node_view


def render_node_query(
    info: Info,
    id: strawberry.ID,
    node_id: strawberry.ID,
) -> Union[types.Pairs, types.Path, types.Table]:


    query = models.NodeQuery.objects.get(id=id)
    
    return render_node_view(info, query, node_id)

