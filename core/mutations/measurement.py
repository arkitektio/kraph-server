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
class MeasurementInput:
    category: strawberry.ID
    structure: scalars.NodeID 
    entity: scalars.NodeID
    valid_from: datetime.datetime | None = None
    valid_to: datetime.datetime | None = None
    context: inputs.ContextInput | None = strawberry.field(
        default=None, description="The context of the measurement"
    )


@strawberry.input
class DeleteMeasurementInput:
    id: strawberry.ID


def create_measurement(
    info: Info,
    input: MeasurementInput,
) -> types.Measurement:

    input_kind = models.MeasurementCategory.objects.get(id=input.category)

    entity_graph_name = node_id_to_graph_name(input.entity)
    entity_id = node_id_to_graph_id(input.entity)

    
    structure_graph_name = node_id_to_graph_name(input.structure)
    structure_id = node_id_to_graph_id(input.structure)
    
    # Assert that the graph name is the same as the input kind
    assert entity_graph_name == structure_graph_name, f"Graph names do not match {entity_graph_name} != {structure_graph_name}"

    measurement = age.create_measurement(
        input_kind,
        structure_id,
        entity_id,
        valid_from=input.valid_from,
        valid_to=input.valid_to,
        assignation_id=None,
        created_by=info.context.request.user.id,
        created_at=datetime.datetime.now(),
    )

    return types.Measurement(_value=measurement)


def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
