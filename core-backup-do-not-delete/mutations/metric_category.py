from kante.types import Info

import strawberry
from core import types, models, enums, scalars, manager, inputs
from core import age


@strawberry.input(description="Input for creating a new expression")
class MetricCategoryInput(inputs.CategoryInput, inputs.NodeCategoryInput):
    graph: strawberry.ID = strawberry.field(description="The ID of the graph")
    structure_category: strawberry.ID | None = strawberry.field(default=None, description="The structure category that this metric describes")
    structure_identifier: scalars.StructureIdentifier | None = strawberry.field(
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


def metric_category_creator(
    info: Info,
    graph_id: str,
    label: str,
    structure_category_id: str | None = None,
    structure_identifier: str | None = None,
    description: str | None = None,
    purl: str | None = None,
    metric_kind: enums.MetricKind | None = None,
    property_definitions: list | None = None,
    tags: list[str] | None = None,
    sequence: str | None = None,
    auto_create_sequence: bool = False,
    position_x: float | None = None,
    position_y: float | None = None,
    height: float | None = None,
    width: float | None = None,
) -> types.MetricCategory:
    """Core creator function for metric categories."""
    graph = models.Graph.objects.get(id=graph_id)

    if structure_category_id is None and structure_identifier is None:
        raise ValueError("Either structure_category_id or structure_identifier must be provided")

    if structure_category_id:
        x = models.StructureCategory.objects.get(id=structure_category_id)
    else:
        x = models.StructureCategory.objects.get_or_create(
            graph=graph,
            age_name=manager.build_structure_age_name(structure_identifier),
            defaults=dict(
                identifier=structure_identifier,
            ),
        )[0]

    metric_category, created = models.MetricCategory.objects.update_or_create(
        graph=graph,
        age_name=manager.build_metric_age_name(label, x.age_name),
        defaults=dict(
            description=description,
            purl=purl,
            metric_kind=metric_kind,
            structure_category=x,
            label=label,
            property_definitions=property_definitions or [],
        ),
    )

    age.create_age_metric_kind(metric_category)
    manager.set_age_sequence(metric_category, sequence, auto_create=auto_create_sequence)

    if position_x is not None:
        metric_category.position_x = position_x
    if position_y is not None:
        metric_category.position_y = position_y
    if height is not None:
        metric_category.height = height
    if width is not None:
        metric_category.width = width
    if any([position_x is not None, position_y is not None, height is not None, width is not None]):
        metric_category.save()

    if tags:
        metric_category.tags.clear()
        for tag in tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=graph)
            metric_category.tags.add(tag_obj)

    return metric_category


def create_metric_category(
    info: Info,
    input: MetricCategoryInput,
) -> types.MetricCategory:
    """GraphQL mutation wrapper for creating metric categories."""
    return metric_category_creator(
        info=info,
        graph_id=input.graph,
        label=input.label,
        structure_category_id=input.structure_category,
        structure_identifier=input.structure_identifier,
        description=input.description,
        purl=input.purl,
        metric_kind=input.kind,
        property_definitions=[strawberry.asdict(x) for x in input.property_definitions] if input.property_definitions else None,
        tags=input.tags,
        sequence=input.sequence,
        auto_create_sequence=input.auto_create_sequence or False,
        position_x=input.position_x,
        position_y=input.position_y,
        height=input.height,
        width=input.width,
    )


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
