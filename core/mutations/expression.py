from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings

@strawberry.input
class ExpressionInput:
    ontology: strawberry.ID | None = None
    label: str
    description: str | None = None
    purl: str | None = None
    color: list[int] | None = None
    kind: enums.ExpressionKind
    metric_kind: enums.MetricDataType | None = None
    image: Upload | None = None


@strawberry.input
class UpdateExpressionInput:
    id: strawberry.ID
    label: str | None = None
    description: str | None = None
    purl: str | None = None
    color: list[int] | None = None
    image: strawberry.ID | None = None


@strawberry.input
class DeleteExpressionInput:
    id: strawberry.ID



def create_expression(
    info: Info,
    input: ExpressionInput,
) -> types.Expression:
    
    ontology = models.Ontology.objects.get(id=input.ontology) if input.ontology else None

    if not ontology:

        user = info.context.request.user
    
        ontology, _ = models.Ontology.objects.get_or_create(
            user=user,
            defaults=dict(name="Default for {}".format(user.username),
            description="Default ontology for {}".format(user.username),)
        )


    if input.color:
        assert len(input.color) == 3 or len(input.color) == 4, "Color must be a list of 3 or 4 values RGBA"

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None


    vocab, _ = models.Expression.objects.update_or_create(
        ontology=ontology,
        label=input.label,
        kind=input.kind,
        metric_kind=input.metric_kind,
        defaults=dict(
            description=input.description,
            purl=input.purl,
            store=media_store,
        )
    )



   
    

    return vocab


def update_expression(info: Info, input: UpdateExpressionInput) -> types.Expression:
    item = models.Expression.objects.get(id=input.id)

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

    item.save()
    return item
        


def delete_expression(
    info: Info,
    input: DeleteExpressionInput,
) -> strawberry.ID:
    item = models.Expression.objects.get(id=input.id)
    item.delete()
    return input.id

