from kante.types import Info
import strawberry
from core import types, models, age, scalars


@strawberry.input
class NodeImport:
    category_id: strawberry.ID = strawberry.field(description="The ID of the category to import entities into")
    import_id: str = strawberry.field(description="A unique identifier for the node used to reference it in relations")
    properties: scalars.MetricMap = strawberry.field(description="List of nodes to import (list of properties)")


@strawberry.input
class EdgeImport:
    category_id: strawberry.ID = strawberry.field(description="The ID of the category to import relations into")
    import_id_from: str = strawberry.field(description="The import ID of the source node")
    import_id_to: str = strawberry.field(description="The import ID of the target node")
    import_id: str = strawberry.field(description="A unique identifier for the relation")
    properties: scalars.MetricMap = strawberry.field(description="Properties to set on the relation")


@strawberry.input(description="Input type for creating a new entity")
class ImportGraphInput:
    graph: strawberry.ID = strawberry.field(description="The ID of the graph to import into")
    nodes: list[NodeImport] = strawberry.field(description="List of nodes to import")
    edges: list[EdgeImport] = strawberry.field(description="List of edges to import")


def import_graph(
    info: Info,
    input: ImportGraphInput,
) -> types.Graph:
    selected_graph = models.Graph.objects.get(id=input.graph)

    fetched_categories = {}

    for node in input.nodes:
        if node.category_id not in fetched_categories:
            cat = models.NodeCategory.objects.get(id=node.category_id)
            fetched_categories[node.category_id] = cat
            assert cat.graph == selected_graph, "Node category does not belong to the selected graph"

    for edge in input.edges:
        if edge.category_id not in fetched_categories:
            rel = models.EdgeCategory.objects.get(id=edge.category_id)
            fetched_categories[edge.category_id] = rel
            assert rel.graph == selected_graph, "Relation category does not belong to the selected graph"

    imported_nodes = {}

    for node in input.nodes:
        category = fetched_categories[node.category_id]
        graph_node = age.create_age_entity(
            category=category,
            external_id=node.import_id,
            properties=node.properties,
            created_by=str(info.context.request.user.id) if info.context.request.user and hasattr(info.context.request.user, "id") else None,
        )
        imported_nodes[node.import_id] = graph_node

    for edge in input.edges:
        category = fetched_categories[edge.category_id]
        from_node = imported_nodes.get(edge.import_id_from)
        to_node = imported_nodes.get(edge.import_id_to)
        if not from_node or not to_node:
            raise ValueError("Referenced nodes for relation import not found")

        print(from_node, to_node)
        age.create_age_relation(
            category=category,
            left_id=from_node.id,
            right_id=to_node.id,
        )

    return selected_graph
