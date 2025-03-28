from kante.types import Info
from core.utils import node_id_to_graph_id, node_id_to_graph_name, scalar_string_to_graph_name
import strawberry
from core import types, models, age, inputs, scalars, enums
import uuid
import datetime
import re


@strawberry.input
class InputMapping:
    key: str
    node: strawberry.ID



@strawberry.input
class RecordNaturalEventInput:
    category: strawberry.ID
    sources: list[InputMapping] | None = None
    targets: list[InputMapping] | None = None
    supporting_structure: scalars.StructureIdentifier | None = None
    


@strawberry.input
class DeleteMeasurementInput:
    id: strawberry.ID

def record_natural_event(
    info: Info,
    input: RecordNaturalEventInput,
) -> types.Metric:
    
    if not input.supporting_structure:
        #TODO: Implement a way to create a supporting structure
        raise ValueError("Supporting structure is required")

    
    structure_name, structure_identifier, structure_object = scalar_string_to_graph_name(input.structure)
    
    metric_category = models.NaturalEventCategory.objects.get(
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

    return types.Metric(_value=id)

















def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
