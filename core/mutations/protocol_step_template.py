import datetime
from kante.types import Info
import strawberry
from core import types, models, scalars, age, enums
import uuid



@strawberry.input
class PlateChildInput:
    id: strawberry.ID | None = None
    type: str | None = None
    text: str | None = None
    children: list["PlateChildInput"] | None = None
    value: str | None = None
    color: str | None = None
    fontSize: str | None = None
    backgroundColor: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None




@strawberry.input
class ProtocolStepTemplateInput:
    name: str
    plate_children: list[PlateChildInput]


@strawberry.input
class UpdateProtocolStepTemplateInput:
    id: strawberry.ID
    name: str  | None = None
    plate_children: list[PlateChildInput]




@strawberry.input
class DeleteProtocolStepTemplateInput:
    id: strawberry.ID



def create_protocol_step_template(
    info: Info,
    input: ProtocolStepTemplateInput,
) -> types.ProtocolStepTemplate:
    


    step = models.ProtocolStepTemplate.objects.create(
        name=input.name,
        plate_children=[strawberry.asdict(i) for i in input.plate_children],
        creator=info.context.request.user

    )

    return step


def child_to_str(child):
    if child.get("children", []) is None:
        return " ".join([child_to_str(c) for c in child["children"]]),
    else:
        return child.get("value", child.get("text", "")) or ""


def plate_children_to_str(children):
    return " ".join([child_to_str(c) for c in children])


def update_protocol_step_template(
    info: Info,
    input: UpdateProtocolStepTemplateInput,
) -> types.ProtocolStepTemplate:
    step = models.ProtocolStepTemplate.objects.get(id=input.id)
    step.plate_children = [strawberry.asdict(i) for i in input.plate_children] if input.plate_children else step.plate_children


    step.save()
    return step


def delete_protocol_step_template(
    info: Info,
    input: DeleteProtocolStepTemplateInput,
) -> strawberry.ID:
    item = models.ProtocolStepTemplate.objects.get(id=input.id)
    item.delete()
    return input.id

