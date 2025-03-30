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


@strawberry.input
class RecordNaturalEventInput:
    category: strawberry.ID
    entity_sources: list[inputs.NodeMapping] | None = None
    entity_targets: list[inputs.NodeMapping] | None = None
    supporting_structure: strawberry.ID | None = None
    external_id: str | None = None
    valid_from: datetime.datetime | None = None
    valid_to: datetime.datetime | None = None


@strawberry.input
class DeleteMeasurementInput:
    id: strawberry.ID


def record_natural_event(
    info: Info,
    input: RecordNaturalEventInput,
) -> types.NaturalEvent:

    
    natural_event = models.NaturalEventCategory.objects.get(id=input.category)

    # TODO: VALIDATE EVERYTHING

    natural_event_entity = age.create_age_natural_event(
        natural_event,
        external_id=input.external_id,
        valid_from=input.valid_from,
        valid_to=input.valid_to,
    )

    necessary_inedges = []
    necessary_outedges = []

    if input.entity_sources:
        necessary_inedges += get_nessessary_inedges(
            natural_event.source_entity_roles,
            input.entity_sources,
            models.EntityCategory.objects,
        )
    if input.entity_targets:
        necessary_outedges += get_nessessary_outedges(
            natural_event.target_entity_roles,
            input.entity_targets,
            models.EntityCategory.objects,
        )

    for edge in necessary_inedges:
        age.create_age_event_in_edge(natural_event, natural_event_entity, edge)

    for edge in necessary_outedges:
        age.create_age_event_out_edge(natural_event, natural_event_entity, edge)

    # TODO: Create the protocol event with the variables and mappings

    return types.NaturalEvent(_value=natural_event_entity)


def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
