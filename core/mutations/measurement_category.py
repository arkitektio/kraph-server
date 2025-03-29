from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class MeasurementCategoryInput:
    graph: strawberry.ID | None = strawberry.field(
        default=None,
        description="The ID of the ontology this expression belongs to. If not provided, uses default ontology",
    )
    label: str = strawberry.field(description="The label/name of the expression")
    description: str | None = strawberry.field(
        default=None, description="A detailed description of the expression"
    )
    purl: str | None = strawberry.field(
        default=None, description="Permanent URL identifier for the expression"
    )
    color: list[int] | None = strawberry.field(
        default=None, description="RGBA color values as list of 3 or 4 integers"
    )
    image: scalars.RemoteUpload | None = strawberry.field(
        default=None, description="An optional image associated with this expression"
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateMeasurementCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )
    label: str | None = strawberry.field(
        default=None, description="New label for the expression"
    )
    description: str | None = strawberry.field(
        default=None, description="New description for the expression"
    )
    purl: str | None = strawberry.field(
        default=None, description="New permanent URL for the expression"
    )
    color: list[int] | None = strawberry.field(
        default=None, description="New RGBA color values as list of 3 or 4 integers"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="New image ID for the expression"
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteMeasurementCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_measurement_category(
    info: Info,
    input: MeasurementCategoryInput,
) -> types.MeasurementCategory:

    graph = models.Graph.objects.get(
        id=input.ontology,
    ) 
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

    vocab, created = models.MeasurementCategory.objects.update_or_create(
        graph=graph,
        age_name=manager.build_relation_age_name(input.label),
        defaults=dict(
            description=input.description,
            purl=input.purl,
            store=media_store,
            label=input.label,
        ),
    )
    
    
    if input.tags:
        vocab.tags.clear()
        for tag in input.tags:
            tag_obj = models.CategoryTag.objects.get(value=tag)
            vocab.tags.add(tag_obj)
    
    
    
    manager.rebuild_graph(vocab.graph)

    return vocab


def update_measurement_category(info: Info, input: UpdateMeasurementCategoryInput) -> types.MeasurementCategory:
    item = models.MeasurementCategory.objects.get(id=input.id)

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


def delete_measurement_category(
    info: Info,
    input: DeleteMeasurementCategoryInput,
) -> strawberry.ID:
    item = models.MeasurementCategory.objects.get(id=input.id)
    item.delete()
    return input.id
