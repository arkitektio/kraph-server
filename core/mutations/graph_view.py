from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings




@strawberry.input(description="Input for creating a new expression")
class GraphViewInput:
    query: strawberry.ID
    graph: strawberry.ID
    


def create_graph_view(
    info: Info,
    input: GraphViewInput,
) -> types.GraphView:


    
    graph_view, _ = models.GraphView.objects.get_or_create(
        graph=models.Graph.objects.get(id=input.graph),
        query=models.GraphQuery.objects.get(id=input.query),
        creator = info.context.request.user,
    )

    

    return graph_view