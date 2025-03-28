from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings



@strawberry.input(description="Input for creating a new expression")
class Filter:
    key: str = strawberry.field(description="The key of the filter")
    value: str = strawberry.field(description="The value of the filter")
    


@strawberry.input(description="Input for creating a new expression")
class PortDefinition:
    param: str = strawberry.field(description="The parameter name")
    tag_filters: list[str] = strawberry.field(
        default=None,
        description="A list of tags to filter the entities",
    ) 
    class_filters: list[str] = strawberry.field(
        default=None,
        description="A list of classes to filter the entities",
    )
    
    


@strawberry.input(description="Input for creating a new expression")
class NaturalEventCategoryInput(inputs.CategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    kind: enums.MetricKind = strawberry.field(
        default=None, description="The type of metric data this expression represents"
    )
    source_definitions: list[PortDefinition] = strawberry.field(
        default=None,
        description="The source definitions for this expression",
    )
    target_definitions: list[PortDefinition] = strawberry.field(
        default=None,
        description="The target definitions for this expression",
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateNaturalEventCategoryInput(NaturalEventCategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    kind: enums.MetricKind = strawberry.field(
        default=None, description="The type of metric data this expression represents"
    )
    structure: scalars.StructureIdentifier = strawberry.field(
        default=None, description="The structure this expression belongs to"
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteMeasurementCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_natural_event_category(
    info: Info,
    input: NaturalEventCategoryInput,
) -> types.MetricCategory:


    protocol_event, created = models.ProtocolEventCategory.objects.update_or_create(
        graph_id=input.graph,
        age_name=manager.build_measurement_age_name(input.label),
        defaults=dict(
            description=input.description,
            purl=input.purl,
            store=media_store,
            label=input.label,
            metric_kind=input.kind,
        ),
        vars=dict(
            source_definitions=[strawberry.asdict(v) for v in input.source_definitions]
        )
    )
    
    for port in input.source_definitions:
        available_ports = models.EntityCategory.objects.filter(
            tags__in=port.tag_filters,
            age_name___in=port.class_filters,
        )
        
        for available_port in available_ports:
            x = models.ParticipantCategory.objects.update_or_create(
                graph_id=input.graph,
                age_name=manager.build_participant_age_name(input.label),
                defaults=dict(
                    needs_quantity=port.needs_quantity,
                ),
            )
            
    for port in input.target_definitions:
        available_ports = models.EntityCategory.objects.filter(
            tags__in=port.tag_filters,
            age_name___in=port.class_filters,
        )
        
        for available_port in available_ports:
            x = models.ParticipantCategory.objects.update_or_create(
                graph_id=input.graph,
                age_name=manager.build_participant_age_name(input.label),
                defaults=dict(
                    needs_quantity=port.needs_quantity,
                ),
            )
    
    
    manager.rebuild_graph(protocol_event.graph)

    return protocol_event


def update_metric_category(info: Info, input: UpdateMeasurementCategoryInput) -> types.MetricCategory:
    item = models.MetricCategory.objects.get(id=input.id)

    if input.color:
        assert (
            len(input.color) == 3 or len(input.color) == 4
        ), "Color must be a list of 3 or 4 values RGBA"

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    item.label = input.label if input.label else item.label
    item.description = input.description if input.description else item.description
    item.purl = input.purl if input.purl else item.purl
    item.color = input.color if input.color else item.color
    item.store = media_store if media_store else item.store

    item.save()
    return item


def delete_measurement_category(
    info: Info,
    input: DeleteMeasurementCategoryInput,
) -> strawberry.ID:
    item = models.MeasurementCategory.objects.get(id=input.id)
    item.delete()
    return input.id
