from kante.types import Info
from core.utils import node_id_to_graph_id, node_id_to_graph_name, scalar_string_to_graph_name
import strawberry
from core import types, models, age, inputs, scalars, enums
import uuid
import datetime
import re





@strawberry.input
class MetricInput:
    structure: scalars.StructureIdentifier
    category: strawberry.ID
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

    
    structure_name, structure_identifier, structure_object = scalar_string_to_graph_name(input.structure)
    
    metric_category = models.MetricCategory.objects.get(
        id=input.category
    )


    id = age.create_age_metric(
        metric_category.graph.age_name,
        metric_category.age_name,
        structure_identifier=structure_identifier,
        structure_object=structure_object,
        value=input.value,
        assignation_id=None,
        created_by=info.context.request.user,
    )

    return types.Metric(_value=id)

















def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
