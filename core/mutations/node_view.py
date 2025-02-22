from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings




@strawberry.input(description="Input for creating a new expression")
class NodeViewInput:
    query: strawberry.ID
    node: strawberry.ID
    


def create_node_view(
    info: Info,
    input: NodeViewInput,
) -> types.NodeView:

    tgraph = models.Graph.objects.get(age_name=age.to_graph_id(input.node))
    print(tgraph.age_name)

    
    view, _ = models.NodeView.objects.get_or_create(
        graph=tgraph,
        node_id=input.node,
        query=models.NodeQuery.objects.get(id=input.query),
        creator = info.context.request.user,
    )

    

    return view