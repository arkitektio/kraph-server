from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs, validators
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for updating an existing expression")
class UpdateMeasurementCategoryInput:
    id: strawberry.ID = strawberry.field(description="The ID of the expression to update")
    label: str | None = strawberry.field(default=None, description="New label for the expression")
    description: str | None = strawberry.field(default=None, description="New description for the expression")
    purl: str | None = strawberry.field(default=None, description="New permanent URL for the expression")
    color: list[int] | None = strawberry.field(default=None, description="New RGBA color values as list of 3 or 4 integers")
    image: strawberry.ID | None = strawberry.field(default=None, description="New image ID for the expression")


@strawberry.input(description="Input for deleting an expression")
class DeleteMeasurementCategoryInput:
    id: strawberry.ID = strawberry.field(description="The ID of the expression to delete")


def measurement_category_creator(
    info: Info,
    graph_id: str,
    label: str,
    description: str | None = None,
    purl: str | None = None,
    color: list[int] | None = None,
    image_id: str | None = None,
    structure_definition: dict | None = None,
    entity_definition: dict | None = None,
    tags: list[str] | None = None,
) -> types.MeasurementCategory:
    """Core creator function for measurement categories."""
    graph = models.Graph.objects.get(id=graph_id)

    if color:
        assert len(color) == 3 or len(color) == 4, "Color must be a list of 3 or 4 values RGBA"

    media_store = None
    if image_id:
        media_store = models.MediaStore.objects.get(id=image_id)

    vocab, created = models.MeasurementCategory.objects.update_or_create(
        graph=graph,
        age_name=manager.build_measurement_age_name(label),
        defaults=dict(
            description=description,
            purl=purl,
            store=media_store,
            label=label,
            source_definition=structure_definition,
            target_definition=entity_definition,
        ),
    )

    age.create_age_measurement_kind(vocab)

    if tags:
        vocab.tags.clear()
        for tag in tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=graph)
            vocab.tags.add(tag_obj)

    return vocab


def create_measurement_category(
    info: Info,
    input: inputs.MeasurementCategoryInput,
) -> types.MeasurementCategory:
    """GraphQL mutation wrapper for creating measurement categories."""
    graph = models.Graph.objects.get(id=input.graph)

    return measurement_category_creator(
        info=info,
        graph_id=input.graph,
        label=input.label,
        description=input.description,
        purl=input.purl,
        color=input.color,
        image_id=input.image,
        structure_definition=validators.validate_structure_definition(input.structure_definition, graph) if input.structure_definition else None,
        entity_definition=validators.validate_entity_definition(input.entity_definition, graph) if input.entity_definition else None,
        tags=input.tags,
    )


def update_measurement_category(info: Info, input: UpdateMeasurementCategoryInput) -> types.MeasurementCategory:
    item = models.MeasurementCategory.objects.get(id=input.id)

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

    if input.tags:
        item.tags.clear()
        for tag in input.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=item.graph)
            item.tags.add(tag_obj)

    item.save()
    return item


def delete_measurement_category(
    info: Info,
    input: DeleteMeasurementCategoryInput,
) -> strawberry.ID:
    item = models.MeasurementCategory.objects.get(id=input.id)
    item.delete()
    return input.id
