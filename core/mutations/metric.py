from kante.types import Info
from core.utils import (
    node_id_to_graph_id,
    node_id_to_graph_name,
    scalar_string_to_graph_name,
)
import strawberry
from core import types, models, age, inputs, scalars, enums
import uuid
import datetime
import re


@strawberry.input
class MetricInput:
    structure: scalars.NodeID
    category: strawberry.ID
    value: scalars.Any = strawberry.field(
        description="The value of the measurement"
    )
    context: inputs.ContextInput | None = strawberry.field(
        default=None, description="The context of the measurement"
    )
   
    # value: scalars.Metric


@strawberry.input
class DeleteMeasurementInput:
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
        value=input.value,
        assignation_id=None,
        created_by=info.context.request.user.id,
    )

    return types.Metric(_value=value)


def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
