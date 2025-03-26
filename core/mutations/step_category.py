from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class StepCategoryInput:
    template: strawberry.ID = strawberry.field(
        description="The ID of the protocol template this expression belongs to"
    )
    ontology: strawberry.ID | None = strawberry.field(
        default=None,
        description="The ID of the ontology this expression belongs to. If not provided, uses default ontology",
    )
    color: list[int] | None = strawberry.field(
        default=None, description="RGBA color values as list of 3 or 4 integers"
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateStepCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )
    template: strawberry.ID | None = strawberry.field(
        default=None, description="New step for the expression"
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
class DeleteStepCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_step_category(
    info: Info,
    input: StepCategoryInput,
) -> types.StepCategory:

    ontology = (
        models.Ontology.objects.get(id=input.ontology) if input.ontology else None
    )

    if not ontology:

        user = info.context.request.user

        ontology, _ = models.Ontology.objects.get_or_create(
            user=user,
            defaults=dict(
                name="Default for {}".format(user.username),
                description="Default ontology for {}".format(user.username),
            ),
        )

    if input.color:
        assert (
            len(input.color) == 3 or len(input.color) == 4
        ), "Color must be a list of 3 or 4 values RGBA"

    vocab, _ = models.StepCategory.objects.update_or_create(
        ontology=ontology,
        age_name=manager.build_step_age_name(input.label),
        defaults=dict(
            template=models.ProtocolTemplate.objects.get(id=input.template),
        ),
    )
    
    
    for i in ontology.graphs.all():
        manager.rebuild_graph(i)

    return vocab


def update_step_category(info: Info, input: UpdateStepCategoryInput) -> types.StepCategory:
    item = models.StepCategory.objects.get(id=input.id)

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

    item.template = models.ProtocolTemplate.objects.get(id=input.template)

    item.save()
    return item


def delete_step_category(
    info: Info,
    input: DeleteStepCategoryInput,
) -> strawberry.ID:
    item = models.StepCategory.objects.get(id=input.id)
    item.delete()
    return input.id
