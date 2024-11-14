from kante.types import Info
import strawberry
from core import types, models, age
import uuid


@strawberry.input(description="Input type for creating a new entity")
class EntityInput:
    kind: strawberry.ID = strawberry.field(
        description="The ID of the kind (LinkedExpression) to create the entity from"
    )
    group: strawberry.ID | None = strawberry.field(
        default=None, description="Optional group ID to associate the entity with"
    )
    parent: strawberry.ID | None = strawberry.field(
        default=None, description="Optional parent entity ID"
    )
    instance_kind: str | None = strawberry.field(
        default=None, description="Optional instance kind specification"
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

    input_kind = models.LinkedExpression.objects.get(id=input.kind)

    id = age.create_age_entity(
        input_kind.graph.age_name, input_kind.age_name, name=input.name
    )

    return types.Entity(_value=id)


def delete_entity(
    info: Info,
    input: DeleteEntityInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
