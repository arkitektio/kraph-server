from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class NaturalEventCategoryInput(inputs.CategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    source_entity_roles: list[inputs.EntityRoleDefinitionInput] = strawberry.field(
        default=None,
        description="The source definitions for this expression",
    )
    target_entity_roles: list[inputs.EntityRoleDefinitionInput] = strawberry.field(
        default=None,
        description="The target definitions for this expression",
    )
    support_definition: inputs.CategoryDefinitionInput = strawberry.field(
        default=None,
        description="The support definition for this expression",
    )
    plate_children: list[inputs.PlateChildInput] | None = strawberry.field(
        default=None,
        description="A list of children for the plate",
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateNaturalEventCategoryInput(NaturalEventCategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    kind: enums.MetricKind = strawberry.field(
        default=None, description="The type of metric data this expression represents"
    )
    structure: scalars.StructureIdentifier = strawberry.field(
        default=None, description="The structure this expression belongs to"
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteNaturalEventCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_natural_event_category(
    info: Info,
    input: NaturalEventCategoryInput,
) -> types.NaturalEventCategory:

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    protocol_event, created = models.NaturalEventCategory.objects.update_or_create(
        graph_id=input.graph,
        age_name=manager.build_measurement_age_name(input.label),
        defaults=dict(
            description=input.description,
            purl=input.purl,
            store=media_store,
            label=input.label,
            source_entity_roles=[
                strawberry.asdict(v) for v in input.source_entity_roles
            ],
            target_entity_roles=[
                strawberry.asdict(v) for v in input.target_entity_roles
            ],
        ),
    )

    if input.tags:
        protocol_event.tags.clear()
        for tag in input.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag)
            protocol_event.tags.add(tag_obj)

    age.create_age_natural_event_kind(
        protocol_event,
    )

    return protocol_event


def update_natural_event_category(
    info: Info, input: UpdateNaturalEventCategoryInput
) -> types.NaturalEventCategory:
    item = models.NaturalEventCategory.objects.get(id=input.id)

    if input.color:
        assert (
            len(input.color) == 3 or len(input.color) == 4
        ), "Color must be a list of 3 or 4 values RGBA"

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    item.label = input.label if input.label else item.label
    item.description = input.description if input.description else item.description
    item.purl = input.purl if input.purl else item.purl
    item.color = input.color if input.color else item.color
    item.store = media_store if media_store else item.store

    item.save()
    return item


def delete_natural_event_category(
    info: Info,
    input: DeleteNaturalEventCategoryInput,
) -> strawberry.ID:
    item = models.NaturalEventCategory.objects.get(id=input.id)
    item.delete()
    return input.id
