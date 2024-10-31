from kante.types import Info
import strawberry
from core import types, models, scalars


@strawberry.input
class ReagentInput:
    lot_id: str
    expression: strawberry.ID


@strawberry.input
class PinReagentInput:
    id: strawberry.ID
    pin: bool


def pin_reagent(
    info: Info,
    input: PinReagentInput,
) -> types.Reagent:
    raise NotImplementedError("TODO")


@strawberry.input
class DeleteReagentInput:
    id: strawberry.ID


def create_reagent(
    info: Info,
    input: ReagentInput,
) -> types.Reagent:
    view, _ = models.Reagent.objects.get_or_create(
        lot_id=input.lot_id,
        expression_id=input.expression,
    )
    return view


def delete_reagent(
    info: Info,
    input: DeleteReagentInput,
) -> strawberry.ID:
    item = models.Reagent.objects.get(id=input.id)
    item.delete()
    return input.id

