from kante.types import Info
from core.utils import node_id_to_graph_id, node_id_to_graph_name
import strawberry
from core import types, models, age, inputs, scalars, enums
import uuid
import datetime
import re





@strawberry.input
class MeasurementInput:
    structure: scalars.NodeID
    entity: scalars.NodeID
    expression: strawberry.ID 
    value: scalars.Metric | None = None
    valid_from: datetime.datetime | None = None
    valid_to: datetime.datetime | None = None



@strawberry.input
class DeleteMeasurementInput:
    id: strawberry.ID

def create_measurement(
    info: Info,
    input: MeasurementInput,
) -> types.Measurement:

    graph_structure = node_id_to_graph_name(input.structure)
    graph_entity = node_id_to_graph_name(input.entity)
    
    assert graph_structure == graph_entity, f"Cannot create a measurement between entities in different graphs {graph_structure} != {graph_entity}"


    graph = models.Graph.objects.get(age_name=graph_structure)  
    
    
    linked_expression = models.Expression.objects.get(
        ontology=graph.ontology,
        id=input.expression
    )
    
    
    #TODO: Get correlation ID from the request
    #TODO: 

    id = age.create_age_measurement(
        graph.age_name,
        linked_expression.age_name,
        structure = node_id_to_graph_id(input.structure),
        entity = node_id_to_graph_id(input.entity),
        value=input.value,
        valid_from=input.valid_from,
        valid_to=input.valid_to,
    )

    return types.Measurement(_value=id)

















def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
