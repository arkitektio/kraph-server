from kante.types import Info
import strawberry
from core import types, models, age
import uuid


@strawberry.input(description="Input type for creating a new entity")
class EntityInput:
    graph: strawberry.ID
    expression: strawberry.ID  = strawberry.field(
        description="The ID of the kind (LinkedExpression) to create the entity from"
    )
    name: str | None = strawberry.field(
        default=None, description="Optional name for the entity"
    )


@strawberry.input
class DeleteEntityInput:
    id: strawberry.ID


def create_entity(
    info: Info,
    input: EntityInput,
) -> types.Entity:

    print(input)
    
    graph = models.Graph.objects.get(id=input.graph)
    input_kind = models.Expression.objects.get(id=input.expression)

    id = age.create_age_entity(
        graph.age_name, input_kind.age_name, name=input.name
    )

    return types.Entity(_value=id)


def delete_entity(
    info: Info,
    input: DeleteEntityInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
