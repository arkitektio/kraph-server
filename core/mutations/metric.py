from kante.types import Info
from core.utils import (
    node_id_to_graph_id,
    node_id_to_graph_name,
    scalar_string_to_graph_name,
)
from core.mutations.structure import scalar_string_to_graph_name
import strawberry
from core import types, models, age, inputs, scalars, enums, manager
import uuid
import datetime
import re
from koherent.vars import get_current_assignation_id

@strawberry.input
class MetricInput:
    structure: scalars.NodeID
    category: strawberry.ID
    value: scalars.Any = strawberry.field(description="The value of the measurement")
    context: inputs.ContextInput | None = strawberry.field(default=None, description="The context of the measurement")

    # value: scalars.Metric


@strawberry.input
class DeleteMetricInput:
    id: strawberry.ID


def create_metric(
    info: Info,
    input: MetricInput,
) -> types.Metric:
    structure_id = node_id_to_graph_id(input.structure)
    structure_graph_name = node_id_to_graph_name(input.structure)

    metric_category = models.MetricCategory.objects.get(id=input.category)
    assert metric_category.graph.age_name == structure_graph_name, f"Graph names do not match {metric_category.graph.age_name} != {structure_graph_name}"

    value = age.create_age_metric(
        metric_category,
        structure_id=structure_id,
        value=metric_category.validate_input(input.value),
        assignation_id=None,
        created_by=info.context.request.user.id,
        
    )

    return types.Metric(_value=value)


@strawberry.input
class StructureMetricInput:
    structure: scalars.StructureString
    label: str = strawberry.field(description="The name of the measurement")
    description: str | None = strawberry.field(default=None, description="The description of the measurement")
    metric_kind: enums.MetricKind = strawberry.field(default=enums.MetricKind.FLOAT, description="The kind of the metric")
    value: scalars.Any = strawberry.field(description="The value of the measurement")
    graph: strawberry.ID


def create_structure_metric(info: Info, input: StructureMetricInput) -> types.Metric:
    age_name, identifier, entity_id = scalar_string_to_graph_name(input.structure)

    structure_category, _ = models.StructureCategory.objects.update_or_create(
        graph_id=input.graph,
        age_name=manager.build_structure_age_name(identifier),
        defaults=dict(
            description="No Description",
            identifier=identifier,
        ),
    )

    age.create_age_structure_kind(structure_category)

    metric_category, _ = models.MetricCategory.objects.get_or_create(
        graph_id=input.graph,
        age_name=manager.build_metric_age_name(input.label, structure_category.age_name),
        structure_category=structure_category,
        defaults=dict(
            metric_kind=input.metric_kind,
            label=input.label,
            description=input.description or "No Description",
        ),
    )

    age.create_age_metric_kind(metric_category)

    structure = age.create_age_structure(
        structure_category,
        entity_id,
    )

    value = age.create_age_metric(
        metric_category,
        structure_id=structure.id,
        value=metric_category.validate_input(input.value),
        assignation_id=get_current_assignation_id(),
        created_by=info.context.request.user.sub,
        created_app=info.context.request.client.client_id if info.context.request.client else None,
        
    )

    return types.entity_to_node_subtype(value)


def delete_metric(
    info: Info,
    input: DeleteMetricInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
