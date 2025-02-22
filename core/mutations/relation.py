from kante.types import Info
from core.utils import node_id_to_graph_id, node_id_to_graph_name
import strawberry
from core import types, models, age, inputs


@strawberry.input(description="Input type for creating a relation between two entities")
class RelationInput:
    """Input type for creating a relation between two entities"""

    left: strawberry.ID = strawberry.field(
        description="ID of the left entity (format: graph:id)"
    )
    right: strawberry.ID = strawberry.field(
        description="ID of the right entity (format: graph:id)"
    )
    kind: strawberry.ID = strawberry.field(
        description="ID of the relation kind (LinkedExpression)"
    )


@strawberry.input(description="Input type for deleting an entity relation")
class DeleteRelationInput:
    """Input type for deleting an entity relation"""

    id: strawberry.ID = strawberry.field(description="ID of the relation to delete")


def create_relation(
    info: Info,
    input: RelationInput,
) -> types.Relation:

    kind = models.RelationCategory.objects.get(id=input.kind)

    left_graph = node_id_to_graph_name(input.left)
    right_graph = node_id_to_graph_name(input.right)
    

    assert (
        left_graph == right_graph
    ), "Cannot create a relation between entities in different graphs"
    
    
    tleft_graph = models.Graph.objects.get(age_name=left_graph)

    retrieve = age.create_age_relation(
        tleft_graph.age_name, kind.age_name, node_id_to_graph_id(input.left), node_id_to_graph_id(input.left)
    )

    return types.Relation(_value=retrieve)



def delete_relation(
    info: Info,
    input: DeleteRelationInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
