import datetime
from kante.types import Info
import strawberry
from core import types, models, scalars, age, enums
import uuid



@strawberry.input
class ReagentMappingInput:
    reagent: strawberry.ID
    volume: int 

@strawberry.input
class VariableInput:
    key: str
    value: str




@strawberry.input
class ProtocolStepInput:
    template: strawberry.ID 
    entity: strawberry.ID
    reagent_mappings: list[ReagentMappingInput]
    value_mappings: list[VariableInput]
    performed_at: datetime.datetime | None = None
    performed_by: strawberry.ID | None = None


@strawberry.input
class UpdateProtocolStepInput:
    id: strawberry.ID
    name: str
    template: strawberry.ID 
    reagent_mappings: list[ReagentMappingInput]
    value_mappings: list[VariableInput]
    performed_at: datetime.datetime | None = None
    performed_by: strawberry.ID | None = None


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
        performed_by=models.User.objects.get(id=input.performed_by) if input.performed_by else info.context.request.user,
        for_entity_id=input.entity,
    )

    return step


def child_to_str(child):
    if child.get("children", []) is None:
        return " ".join([child_to_str(c) for c in child["children"]]),
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

