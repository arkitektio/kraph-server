from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class MetricCategoryInput(inputs.CategoryInput):
    structure_definition: inputs.CategoryDefinitionInput = strawberry.field(
        default=None,
        description="The structure category for this expression",
    )
    label: str = strawberry.field(description="The label/name of the expression")
    kind: enums.MetricKind = strawberry.field(
        default=None, description="The type of metric data this expression represents"
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdatMetricCategoryInput:
    label: str = strawberry.field(description="The label/name of the expression")
    kind: enums.MetricKind = strawberry.field(
        default=None, description="The type of metric data this expression represents"
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteMetricCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_metric_category(
    info: Info,
    input: MetricCategoryInput,
) -> types.MetricCategory:

    metric_category, created = models.MetricCategory.objects.update_or_create(
        graph_id=input.graph,
        age_name=manager.build_metric_age_name(input.label),
        defaults=dict(
            description=input.description,
            purl=input.purl,
            metric_kind=input.kind,
            structure_definition=strawberry.asdict(
                input.structure_definition,
            ),
            label=input.label,
        ),
    )

    age.create_age_metric_kind(metric_category)

    if input.tags:
        metric_category.tags.clear()
        for tag in input.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag)
            metric_category.tags.add(tag_obj)

    return metric_category


def update_metric_category(
    info: Info, input: UpdatMetricCategoryInput
) -> types.MetricCategory:
    item = models.MetricCategory.objects.get(id=input.id)

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


def delete_metric_category(
    info: Info,
    input: DeleteMetricCategoryInput,
) -> strawberry.ID:
    item = models.MeasurementCategory.objects.get(id=input.id)
    item.delete()
    return input.id
