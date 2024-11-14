from kante.types import Info
import strawberry
from core import types, models, age, inputs


@strawberry.input(description="Input type for creating a relation between two entities")
class EntityRelationInput:
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
class DeleteEntityRelationInput:
    """Input type for deleting an entity relation"""

    id: strawberry.ID = strawberry.field(description="ID of the relation to delete")


def create_entity_relation(
    info: Info,
    input: EntityRelationInput,
) -> types.EntityRelation:

    kind = models.LinkedExpression.objects.get(id=input.kind)

    left_graph, left_id = input.left.split(":")
    right_graph, right_id = input.right.split(":")

    assert (
        left_graph == right_graph
    ), "Cannot create a relation between entities in different graphs"

    retrieve = age.create_age_relation(
        kind.graph.age_name, kind.age_name, left_id, right_id
    )

    return types.EntityRelation(_value=retrieve)


@strawberry.input(
    description="Input type for creating a relation between two structures"
)
class StructureRelationInput:
    """Input type for creating a relation between two structures"""

    left: inputs.Structure = strawberry.field(
        description="Left structure of the relation"
    )
    right: inputs.Structure = strawberry.field(
        description="Right structure of the relation"
    )
    kind: strawberry.ID = strawberry.field(
        description="ID of the relation kind (LinkedExpression)"
    )


def create_structure_relation(
    info: Info,
    input: StructureRelationInput,
) -> types.EntityRelation:

    kind = models.LinkedExpression.objects.get(id=input.kind)

    print("Creating relation between", left_graph, left_id, right_graph, right_id)

    assert (
        left_graph == right_graph
    ), "Cannot create a relation between entities in different graphs"

    retrieve = age.create_age_relation(
        kind.graph.age_name, kind.age_name, left_id, right_id
    )

    return types.EntityRelation(_value=retrieve)


def delete_entity_relation(
    info: Info,
    input: DeleteEntityRelationInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
