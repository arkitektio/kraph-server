from kante.types import Info
from core.utils import node_id_to_graph_id, node_id_to_graph_name, scalar_string_to_graph_name
import strawberry
from core import types, models, age, inputs, scalars, enums
import uuid
import datetime
import re





@strawberry.input
class AssociateStructureInput:
    structure: scalars.StructureIdentifier
    entity: scalars.NodeID
    valid_from: datetime.datetime | None = None
    valid_to: datetime.datetime | None = None



@strawberry.input
class DeleteMeasurementInput:
    id: strawberry.ID

def associate_structure(
    info: Info,
    input: AssociateStructureInput,
) -> types.Measurement:

    structure_graph_name, strucuture_identifier, structure_id = scalar_string_to_graph_name(input.structure)
    graph_name = node_id_to_graph_name(input.entity)
    entity_id = node_id_to_graph_id(input.entity)
    

    id = age.associate_structure(
        graph_name,
        strucuture_identifier,
        structure_id,
        entity_id,
        valid_from=input.valid_from,
        valid_to=input.valid_to,
        assignation_id=None,
        created_by=info.context.request.user,
        created_at=datetime.datetime.now(),
        
    )

    return types.Measurement(_value=id)

















def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
