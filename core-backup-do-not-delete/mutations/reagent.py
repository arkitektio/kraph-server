from kante.types import Info
import strawberry
from core import types, models, age
import uuid


@strawberry.input(description="Input type for creating a new entity")
class ReagentInput:
    reagent_category: strawberry.ID = strawberry.field(
        description="The ID of the kind (LinkedExpression) to create the entity from"
    )
    name: str | None = strawberry.field(
        default=None, description="Optional name for the entity"
    )
    external_id: str | None = strawberry.field(
        default=None,
        description="An optional external ID for the entity (will upsert if exists)",
    )
    set_active: bool | None = strawberry.field(
        default=False, description="Set the reagent as active"
    )


@strawberry.input
class DeleteReagentInput:
    id: strawberry.ID


def create_reagent(
    info: Info,
    input: ReagentInput,
) -> types.Reagent:

    input_kind = models.ReagentCategory.objects.get(id=input.reagent_category)

    print(input_kind.graph.age_name)
    id = age.create_age_reagent(
        input_kind, name=input.name, external_id=input.external_id
    )

    if input.set_active:
        age.set_as_active_reagent_for_category(input_kind, id)

    return types.Reagent(_value=id)


def delete_reagent(
    info: Info,
    input: DeleteReagentInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
