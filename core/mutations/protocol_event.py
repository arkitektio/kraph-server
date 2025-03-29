from kante.types import Info
from core.utils import node_id_to_graph_id, node_id_to_graph_name, scalar_string_to_graph_name
import strawberry
from core import types, models, age, inputs, scalars, enums, inputs
import uuid
import datetime
import re


@strawberry.input
class InputMapping:
    key: str
    node: strawberry.ID



@strawberry.input
class RecordProtocolEventInput:
    category: strawberry.ID
    sources: list[inputs.InputMapping] | None = None
    targets: list[inputs.InputMapping] | None = None
    variables: list[inputs.InputMapping] | None = None
    


@strawberry.input
class DeleteMeasurementInput:
    id: strawberry.ID

def record_protocol_event(
    info: Info,
    input: RecordProtocolEventInput,
) -> types.ProtocolEvent:

    
    
    metric_category = models.ProtocolEventCategory.objects.get(
        id=input.category
    )


    id = age.create_age_natural_event(
        metric_category.graph.age_name,
        metric_category.age_name,
        structure_identifier=structure_identifier,
        structure_object=structure_object,
        value=input.value,
        assignation_id=None,
        created_by=info.context.request.user,
    )

    return types.ProtocolEvent(_value=id)

















def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
