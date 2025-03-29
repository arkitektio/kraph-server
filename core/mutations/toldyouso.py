from kante.types import Info
import strawberry
from core import types, models, age, inputs
import uuid


@strawberry.input(description="Input type for creating a new entity")
class ToldYouSoInput:
    reason: str | None = strawberry.field(
        default=None, description="The reason why you made this assumption"
    )
    name: str | None = strawberry.field(
        default=None, description="Optional name for the entity"
    )
    external_id: str | None = strawberry.field(
        default=None, description="An optional external ID for the entity (will upsert if exists)"
    )
    context: inputs.ContextInput | None = strawberry.field(
        default=None, description="The context of the measurement"
    )


@strawberry.input
class DeleteToldYouSoInput:
    id: strawberry.ID


def create_toldyouso(
    info: Info,
    input: ToldYouSoInput,
) -> types.Structure:

    input_kind = models.StructureCategory.objects.get(id=input.expression)

    id = age.create_age_entity(
        input_kind.graph.age_name, input_kind.age_name, name=input.name
    )

    return types.Entity(_value=id)


def delete_toldyouso(
    info: Info,
    input: DeleteToldYouSoInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
