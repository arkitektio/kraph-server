from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs, validators
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class MetricCategoryInput(inputs.CategoryInput, inputs.NodeCategoryInput):
    structure_category: strawberry.ID | None = strawberry.field(
        default=None,
        description="The structure category that this metric describes"
    )
    structure_identifier: scalars.StructureIdentifier | None  = strawberry.field(
        description="The structure identifier within the structure category",
        default=None,
    )
    label: str = strawberry.field(description="The label/name of the expression")
    kind: enums.MetricKind = strawberry.field(default=None, description="The type of metric data this expression represents")


@strawberry.input(description="Input for updating an existing expression")
class UpdateMetricCategoryInput(inputs.UpdateCategoryInput, inputs.NodeCategoryInput):
    kind: enums.MetricKind | None = strawberry.field(default=None, description="The type of metric data this expression represents")
    structure_definition: inputs.StructureCategoryDefinitionInput | None = strawberry.field(
        default=None,
        description="The structure category for this expression",
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteMetricCategoryInput:
    id: strawberry.ID = strawberry.field(description="The ID of the expression to delete")


def create_metric_category(
    info: Info,
    input: MetricCategoryInput,
) -> types.MetricCategory:
    graph = models.Graph.objects.get(
        id=input.graph,
    )
    
    if input.structure_category is None and input.structure_identifier is None:
        raise ValueError("Either structure_category or structure_identifier must be provided")
    
    if input.structure_category:
        x = models.StructureCategory.objects.get(id=input.structure_category),
    else:
        x = models.StructureCategory.objects.get_or_create(
            graph=graph,
            age_name=manager.build_structure_age_name(input.structure_identifier),
            defaults=dict(
                identifier=input.structure_identifier,
            ),
        )[0]

    metric_category, created = models.MetricCategory.objects.update_or_create(
        graph=graph,
        age_name=manager.build_metric_age_name(input.label, x.age_name),
        defaults=dict(
            description=input.description,
            purl=input.purl,
            metric_kind=input.kind,
            structure_category=x,
            label=input.label,
        ),
    )

    age.create_age_metric_kind(metric_category)
    manager.set_age_sequence(metric_category, input.sequence, auto_create=input.auto_create_sequence)
    manager.set_position_info(metric_category, input)

    if input.tags:
        metric_category.tags.clear()
        for tag in input.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=graph)
            metric_category.tags.add(tag_obj)

    return metric_category


def update_metric_category(info: Info, input: UpdateMetricCategoryInput) -> types.MetricCategory:
    item = models.MetricCategory.objects.get(id=input.id)

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


    manager.set_position_info(item, input)

    item.save()
    return item


def delete_metric_category(
    info: Info,
    input: DeleteMetricCategoryInput,
) -> strawberry.ID:
    item = models.MeasurementCategory.objects.get(id=input.id)
    item.delete()
    return input.id
