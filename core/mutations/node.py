from kante.types import Info
import strawberry
from core import models, age


@strawberry.input
class DeleteNodeInput:
    id: strawberry.ID


def delete_node(
    info: Info,
    input: DeleteNodeInput,
) -> strawberry.ID:
    local_id = age.to_entity_id(input.id)
    graph_name = age.to_graph_id(input.id)

    x = models.Graph.objects.get(age_name=graph_name)
    if not x.node_deletion_allowed:
        raise Exception(f"Node deletion is not allowed in graph {graph_name}")
    if not x.organization == info.context.request.organization:
        raise Exception(f"You do not have permission to delete nodes in graph {graph_name}")

    measurement = age.delete_node(graph_name, node_id=local_id)
    return input.id


def detach_delete_node(
    info: Info,
    input: DeleteNodeInput,
) -> strawberry.ID:
    local_id = age.to_entity_id(input.id)
    graph_name = age.to_graph_id(input.id)

    x = models.Graph.objects.get(age_name=graph_name)
    if not x.node_deletion_allowed:
        raise Exception(f"Node deletion is not allowed in graph {graph_name}")
    if not x.organization == info.context.request.organization:
        raise Exception(f"You do not have permission to delete nodes in graph {graph_name}")

    measurement = age.detach_delete_node(graph_name, node_id=local_id)
    return input.id
