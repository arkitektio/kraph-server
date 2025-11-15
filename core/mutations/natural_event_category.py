from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class NaturalEventCategoryInput(inputs.CategoryInput, inputs.NodeCategoryInput):
    graph: strawberry.ID = strawberry.field(description="The ID of the graph")
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
class UpdateNaturalEventCategoryInput(inputs.UpdateCategoryInput, inputs.NodeCategoryInput):
    id: strawberry.ID = strawberry.field(description="The ID of the expression to update")
    label: str | None = strawberry.field(default=None, description="The label/name of the expression")
    source_entity_roles: list[inputs.EntityRoleDefinitionInput] | None = strawberry.field(
        default=None,
        description="The source definitions for this expression",
    )
    target_entity_roles: list[inputs.EntityRoleDefinitionInput] | None = strawberry.field(
        default=None,
        description="The target definitions for this expression",
    )
    support_definition: inputs.CategoryDefinitionInput | None = strawberry.field(
        default=None,
        description="The support definition for this expression",
    )
    plate_children: list[inputs.PlateChildInput] | None = strawberry.field(
        default=None,
        description="A list of children for the plate",
    )
    image: strawberry.ID | None = strawberry.field(
        default=None,
        description="An optional ID reference to an associated image",
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteNaturalEventCategoryInput:
    id: strawberry.ID = strawberry.field(description="The ID of the expression to delete")


def natural_event_category_creator(
    info: Info,
    graph_id: str,
    label: str,
    description: str | None = None,
    purl: str | None = None,
    image_id: str | None = None,
    source_entity_roles: list[dict] | None = None,
    target_entity_roles: list[dict] | None = None,
    tags: list[str] | None = None,
    position_x: float | None = None,
    position_y: float | None = None,
    height: float | None = None,
    width: float | None = None,
) -> types.NaturalEventCategory:
    """Core creator function for natural event categories."""
    media_store = None
    if image_id:
        media_store = models.MediaStore.objects.get(id=image_id)

    source_role_names = [v["role"] for v in source_entity_roles] if source_entity_roles else []
    target_role_names = [v["role"] for v in target_entity_roles] if target_entity_roles else []

    all_roles = source_role_names + target_role_names
    assert len(all_roles) == len(set(all_roles)), "Roles must be unique"

    protocol_event, created = models.NaturalEventCategory.objects.update_or_create(
        graph_id=graph_id,
        age_name=manager.build_measurement_age_name(label),
        defaults=dict(
            description=description,
            purl=purl,
            store=media_store,
            label=label,
            source_entity_roles=source_entity_roles or [],
            target_entity_roles=target_entity_roles or [],
        ),
    )

    if tags:
        protocol_event.tags.clear()
        for tag in tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=protocol_event.graph)
            protocol_event.tags.add(tag_obj)

    age.create_age_natural_event_kind(protocol_event)

    if position_x is not None:
        protocol_event.position_x = position_x
    if position_y is not None:
        protocol_event.position_y = position_y
    if height is not None:
        protocol_event.height = height
    if width is not None:
        protocol_event.width = width
    if any([position_x is not None, position_y is not None, height is not None, width is not None]):
        protocol_event.save()

    return protocol_event


def create_natural_event_category(
    info: Info,
    input: NaturalEventCategoryInput,
) -> types.NaturalEventCategory:
    """GraphQL mutation wrapper for creating natural event categories."""
    return natural_event_category_creator(
        info=info,
        graph_id=input.graph,
        label=input.label,
        description=input.description,
        purl=input.purl,
        image_id=input.image,
        source_entity_roles=[strawberry.asdict(v) for v in input.source_entity_roles] if input.source_entity_roles else None,
        target_entity_roles=[strawberry.asdict(v) for v in input.target_entity_roles] if input.target_entity_roles else None,
        tags=input.tags,
        position_x=input.position_x,
        position_y=input.position_y,
        height=input.height,
        width=input.width,
    )


def update_natural_event_category(info: Info, input: UpdateNaturalEventCategoryInput) -> types.NaturalEventCategory:
    item = models.NaturalEventCategory.objects.get(id=input.id)

    if input.color:
        assert len(input.color) == 3 or len(input.color) == 4, "Color must be a list of 3 or 4 values RGBA"

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

    source_entity_role_names = map(lambda v: v.role, input.source_entity_roles) if input.source_entity_roles else []
    target_entity_role_names = map(lambda v: v.role, input.target_entity_roles) if input.target_entity_roles else []

    all_roles = source_entity_role_names + target_entity_role_names
    assert len(all_roles) == len(set(all_roles)), "Roles must be unique"

    if input.source_entity_roles:
        item.source_entity_roles = [strawberry.asdict(v) for v in input.source_entity_roles]

    if input.target_entity_roles:
        item.target_entity_roles = [strawberry.asdict(v) for v in input.target_entity_roles]

    if input.plate_children:
        item.plate_children = [strawberry.asdict(v) for v in input.plate_children]

    # TODO: Check if we need to kill some events in order to update the source and target entity roles

    manager.set_position_info(item, input)
    item.save()
    return item


def delete_natural_event_category(
    info: Info,
    input: DeleteNaturalEventCategoryInput,
) -> strawberry.ID:
    item = models.NaturalEventCategory.objects.get(id=input.id)
    item.delete()
    return input.id
