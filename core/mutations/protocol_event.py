from kante.types import Info
from core.utils import (
    node_id_to_graph_id,
    node_id_to_graph_name,
    scalar_string_to_graph_name,
)
from .utils import get_nessessary_inedges, get_nessessary_outedges
import strawberry
from core import types, models, age, inputs, scalars, enums, inputs
import uuid
import datetime
import re
from dataclasses import dataclass


@strawberry.input
class RecordProtocolEventInput:
    category: strawberry.ID
    external_id: str | None = None
    entity_sources: list[inputs.NodeMapping] | None = None
    entity_targets: list[inputs.NodeMapping] | None = None
    reagent_sources: list[inputs.NodeMapping] | None = None
    reagent_targets: list[inputs.NodeMapping] | None = None
    variables: list[inputs.VariableMappingInput] | None = None
    valid_from: datetime.datetime | None = None
    valid_to: datetime.datetime | None = None


@strawberry.input
class DeleteMeasurementInput:
    id: strawberry.ID


def record_protocol_event(
    info: Info,
    input: RecordProtocolEventInput,
) -> types.ProtocolEvent:

    protocol_event = models.ProtocolEventCategory.objects.get(id=input.category)

    # TODO: VALIDATE EVERYTHING

    protocol_event_entity = age.create_age_protocol_event(
        protocol_event,
        external_id=input.external_id,
        valid_from=input.valid_from,
        valid_to=input.valid_to,
        variables=input.variables,
    )

    necessary_inedges = []
    necessary_outedges = []

    if input.entity_sources:
        necessary_inedges += get_nessessary_inedges(
            protocol_event.source_entity_roles,
            input.entity_sources,
            models.EntityCategory.objects,
        )
    if input.reagent_sources:
        necessary_inedges += get_nessessary_inedges(
            protocol_event.source_reagent_roles,
            input.reagent_sources,
            models.ReagentCategory.objects,
        )
    if input.entity_targets:
        necessary_outedges += get_nessessary_outedges(
            protocol_event.target_entity_roles,
            input.entity_targets,
            models.EntityCategory.objects,
        )
    if input.reagent_targets:
        necessary_outedges += get_nessessary_outedges(
            protocol_event.target_reagent_roles,
            input.reagent_targets,
            models.ReagentCategory.objects,
        )

    for edge in necessary_inedges:
        age.create_age_event_in_edge(protocol_event, protocol_event_entity, edge)

    for edge in necessary_outedges:
        age.create_age_event_out_edge(protocol_event, protocol_event_entity, edge)

    # TODO: Create the protocol event with the variables and mappings

    return types.ProtocolEvent(_value=protocol_event_entity)


def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
