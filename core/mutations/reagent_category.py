from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class ReagentCategoryInput(inputs.CategoryInput, inputs.NodeCategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")


@strawberry.input(description="Input for updating an existing generic category")
class UpdateReagentCategoryInput(inputs.UpdateCategoryInput, inputs.NodeCategoryInput):
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )


@strawberry.input(description="Input for deleting a generic category")
class DeleteReagentCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_reagent_category(
    info: Info,
    input: ReagentCategoryInput,
) -> types.ReagentCategory:

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

    vocab, created = models.ReagentCategory.objects.update_or_create(
        graph_id=input.graph,
        age_name=manager.build_reagent_age_name(input.label),
        defaults=dict(
            description=input.description,
            purl=input.purl,
            store=media_store,
            label=input.label,
            instance_kind=enums.InstanceKind.ENTITY,
        ),
    )

    age.create_age_reagent_kind(vocab)
    manager.set_age_sequence(vocab, input.sequence, auto_create=input.auto_create_sequence)
    
    if input.tags:
        vocab.tags.clear()
        for tag in input.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag)
            vocab.tags.add(tag_obj)
            
    if input.pin is not None:
        if input.pin:
            vocab.pinned_by.add(info.context.user)
        else:
            vocab.pinned_by.remove(info.context.user)

    manager.set_position_info(vocab, input)
    return vocab


def update_reagent_category(
    info: Info, input: UpdateReagentCategoryInput
) -> types.ReagentCategory:
    item = models.ReagentCategory.objects.get(id=input.id)

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

    
    if input.tags:
        item.tags.clear()
        for tag in input.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag)
            item.tags.add(tag_obj)
            
    if input.pin is not None:
        if input.pin:
            item.pinned_by.add(info.context.request.user)
        else:
            item.pinned_by.remove(info.context.request.user)
            
    manager.set_position_info(item, input)
    item.save()
    return item


def delete_reagent_category(
    info: Info,
    input: DeleteReagentCategoryInput,
) -> strawberry.ID:
    item = models.ReagentCategory.objects.get(id=input.id)
    item.delete()
    return input.id
