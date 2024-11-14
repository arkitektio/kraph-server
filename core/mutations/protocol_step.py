import datetime
from kante.types import Info
import strawberry
from core import types, models, scalars, age, enums
import uuid


@strawberry.input(description="Input type for mapping reagents to protocol steps")
class ReagentMappingInput:
    reagent: strawberry.ID = strawberry.field(description="ID of the reagent to map")
    volume: int = strawberry.field(description="Volume of the reagent in microliters")


@strawberry.input(description="Input type for mapping variables to protocol steps")
class VariableInput:
    key: str = strawberry.field(description="Key of the variable")
    value: str = strawberry.field(description="Value of the variable")


@strawberry.input(description="Input type for creating a new protocol step")
class ProtocolStepInput:
    template: strawberry.ID = strawberry.field(
        description="ID of the protocol step template"
    )
    entity: strawberry.ID = strawberry.field(
        description="ID of the entity this step is performed on"
    )
    reagent_mappings: list[ReagentMappingInput] = strawberry.field(
        description="List of reagent mappings"
    )
    value_mappings: list[VariableInput] = strawberry.field(
        description="List of variable mappings"
    )
    performed_at: datetime.datetime | None = strawberry.field(
        default=None, description="When the step was performed"
    )
    performed_by: strawberry.ID | None = strawberry.field(
        default=None, description="ID of the user who performed the step"
    )


@strawberry.input(description="Input type for updating an existing protocol step")
class UpdateProtocolStepInput:
    id: strawberry.ID = strawberry.field(
        description="ID of the protocol step to update"
    )
    name: str = strawberry.field(description="New name for the protocol step")
    template: strawberry.ID = strawberry.field(
        description="ID of the new protocol step template"
    )
    reagent_mappings: list[ReagentMappingInput] = strawberry.field(
        description="Updated list of reagent mappings"
    )
    value_mappings: list[VariableInput] = strawberry.field(
        description="Updated list of variable mappings"
    )
    performed_at: datetime.datetime | None = strawberry.field(
        default=None, description="When the step was performed"
    )
    performed_by: strawberry.ID | None = strawberry.field(
        default=None, description="ID of the user who performed the step"
    )


@strawberry.input
class DeleteProtocolStepInput:
    id: strawberry.ID


def create_protocol_step(
    info: Info,
    input: ProtocolStepInput,
) -> types.ProtocolStep:

    step = models.ProtocolStep.objects.create(
        template=models.ProtocolStepTemplate.objects.get(id=input.template),
        performed_at=input.performed_at,
        performed_by=(
            models.User.objects.get(id=input.performed_by)
            if input.performed_by
            else info.context.request.user
        ),
        for_entity_id=input.entity,
    )

    return step


def child_to_str(child):
    if child.get("children", []) is None:
        return (" ".join([child_to_str(c) for c in child["children"]]),)
    else:
        return child.get("value", child.get("text", "")) or ""


def plate_children_to_str(children):
    return " ".join([child_to_str(c) for c in children])


def update_protocol_step(
    info: Info,
    input: UpdateProtocolStepInput,
) -> types.ProtocolStep:
    step = models.ProtocolStep.objects.get(id=input.id)

    raise NotImplementedError("Update not implemented yet")

    step.save()
    return step


def delete_protocol_step(
    info: Info,
    input: DeleteProtocolStepInput,
) -> strawberry.ID:
    item = models.ProtocolStep.objects.get(id=input.id)
    item.delete()
    return input.id
