from kante.types import Info
import strawberry
from core import models, age


@strawberry.input
class DeleteEdgeInput:
    id: strawberry.ID


def delete_edge(
    info: Info,
    input: DeleteEdgeInput,
) -> strawberry.ID:
    local_id = age.to_entity_id(input.id)
    graph_name = age.to_graph_id(input.id)

    x = models.Graph.objects.get(age_name=graph_name)
    if not x.edge_deletion_allowed:
        raise Exception(f"Edge deletion is not allowed in graph {graph_name}")
    if not x.organization == info.context.request.organization:
        raise Exception(f"You do not have permission to delete edges in graph {graph_name}")

    measurement = age.delete_edge(graph_name, edge_id=local_id)
    return input.id
