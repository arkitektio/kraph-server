import strawberry
import strawberry_django
from core import models, age, loaders, types


@strawberry.type
class EntityNodeMetric:
    data_kind: str
    kind: str
    metric_id: str
    value: str


@strawberry.type
class EntityNode:
    _value: strawberry.Private[age.RetrievedEntity]
    is_root: bool = False

    @strawberry.field
    def id(self) -> strawberry.ID:
        return self._value.unique_id
    
    @strawberry.field
    def subtitle(self) -> str:
        return self._value.kind_age_name
    
    @strawberry.field
    def label(self) -> str:
        return self._value.id
    
    @strawberry.field
    async def linked_expression(self) -> str:
        return await loaders.linked_expression_loader.load(f"{self._value.graph_name}:{self._value.unique_id}")
    
    @strawberry.field
    def metrics(self) -> list[EntityNodeMetric]:
        return [    ]



@strawberry.type
class EntityGraph:
    _graph: strawberry.Private[str]
    nodes: list[types.Entity]
    edges: list[types.EntityRelation]

    @strawberry_django.field
    def graph(self) -> types.Graph:
        return models.Graph.objects.get(age_name=self._graph)



def entity_graph(id: strawberry.ID) -> EntityGraph:
    """
    Query the knowledge graph for information about a given entity.

    Args:
        query: The entity to search for in the knowledge graph.

    Returns:
        A dictionary containing information about the entity.
    """

    nodes = []
    edges = []


    graph_name, entity_id = id.split(":")

    print(graph_name, entity_id)


    node = age.get_age_entity(graph_name, entity_id)

    nodes, edges = age.get_neighbors_and_edges(graph_name, entity_id)

    entity_nodes = []

    entity_nodes.append(types.Entity(_value=node))

    for node in nodes:

        entity_nodes.append(types.Entity(_value=node))

    entity_edges = []

    for edge in edges:
            
        entity_edges.append(types.EntityRelation(_value=edge))


    assert len(entity_nodes) > 0, "No nodes found"


    print("Retrieved nodes", entity_nodes, entity_edges)


    return EntityGraph(nodes=entity_nodes, edges=entity_edges, _graph=graph_name)