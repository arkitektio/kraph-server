from kante.types import Info
import strawberry
from core import types, models, age
import uuid




@strawberry.input
class EntityInput:
    kind: strawberry.ID
    group: strawberry.ID  | None = None
    parent: strawberry.ID | None = None
    instance_kind: str | None = None
    name: str | None = None


@strawberry.input
class DeleteEntityInput:
    id: strawberry.ID



def create_entity(
    info: Info,
    input: EntityInput,
) -> types.Entity:
    
    print(input)

    input_kind = models.LinkedExpression.objects.get(id=input.kind)



    id = age.create_age_entity(input_kind.graph.age_name, input_kind.age_name, name=input.name)

    return types.Entity(_value=id)


@strawberry.input
class EntityInput:
    kind: strawberry.ID
    group: strawberry.ID  | None = None
    parent: strawberry.ID | None = None
    instance_kind: str | None = None
    name: str | None = None





def create_structure(
    info: Info,
    input: EntityInput,
) -> types.Entity:
    
    print(input)

    input_kind = models.LinkedExpression.objects.get(id=input.kind)



    id = age.create_age_entity(input_kind.graph.age_name, input_kind.age_name, name=input.name)

    return types.Entity(_value=id)











def delete_entity(
    info: Info,
    input: DeleteEntityInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id

