from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs, loaders
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class ProtocolEventCategoryInput(inputs.CategoryInput, inputs.NodeCategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    plate_children: list[inputs.PlateChildInput] | None = strawberry.field(
        default=None,
        description="A list of children for the plate",
    )
    source_entity_roles: list[inputs.EntityRoleDefinitionInput] | None = (
        strawberry.field(
            default=None,
            description="The source definitions for this expression",
        )
    )
    source_reagent_roles: list[inputs.ReagentRoleDefinitionInput] | None = (
        strawberry.field(
            default=None,
            description="The target definitions for this expression",
        )
    )
    target_entity_roles: list[inputs.EntityRoleDefinitionInput] | None = (
        strawberry.field(
            default=None,
            description="The target definitions for this expression",
        )
    )
    target_reagent_roles: list[inputs.ReagentRoleDefinitionInput] | None = (
        strawberry.field(
            default=None,
            description="The target definitions for this expression",
        )
    )
    variable_definitions: list[inputs.VariableDefinitionInput] | None = strawberry.field(
        default=None,
        description="The variable definitions for this expression",
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateProtocolEventCategoryInput(inputs.UpdateCategoryInput, inputs.NodeCategoryInput):
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )
    label: str | None = strawberry.field(
        default=None,
        description="The label/name of the expression",
    )
    plate_children: list[inputs.PlateChildInput] | None = strawberry.field(
        default=None,
        description="A list of children for the plate",
    )
    source_entity_roles: list[inputs.EntityRoleDefinitionInput] | None = (
        strawberry.field(
            default=None,
            description="The source definitions for this expression",
        )
    )
    source_reagent_roles: list[inputs.ReagentRoleDefinitionInput] | None = (
        strawberry.field(
            default=None,
            description="The target definitions for this expression",
        )
    )
    target_entity_roles: list[inputs.EntityRoleDefinitionInput] | None = (
        strawberry.field(
            default=None,
            description="The target definitions for this expression",
        )
    )
    target_reagent_roles: list[inputs.ReagentRoleDefinitionInput] | None = (
        strawberry.field(
            default=None,
            description="The target definitions for this expression",
        )
    )
    variable_definitions: list[inputs.VariableDefinitionInput] | None = strawberry.field(
        default=None,
        description="The variable definitions for this expression",
    )
    image: strawberry.ID | None = strawberry.field(
        default=None,
        description="An optional ID reference to an associated image",
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteProtocolEventCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_protocol_event_category(
    info: Info,
    input: ProtocolEventCategoryInput,
) -> types.ProtocolEventCategory:
    source_entity_role_names = list(map(lambda v: v.role, input.source_entity_roles)) if input.source_entity_roles else []
    target_entity_role_names = list(map(lambda v: v.role, input.target_entity_roles)) if input.target_entity_roles else []
    source_reagent_role_names = list(map(lambda v: v.role, input.source_reagent_roles)) if input.source_reagent_roles else []
    target_reagent_role_names = list(map(lambda v: v.role, input.target_reagent_roles)) if input.target_reagent_roles else []
    variable_params = list(map(lambda v: v.param, input.variable_definitions)) if input.variable_definitions else []
    
    
    all_roles = source_entity_role_names + target_entity_role_names + source_reagent_role_names + target_reagent_role_names + variable_params
    assert len(all_roles) == len(set(all_roles)), "Roles must be unique" 
    

    protocol_event, created = models.ProtocolEventCategory.objects.update_or_create(
        graph_id=input.graph,
        age_name=manager.build_protocol_event_age_name(input.label),
        defaults=dict(
            description=input.description,
            purl=input.purl,
            label=input.label,
            source_entity_roles=(
                [strawberry.asdict(v) for v in input.source_entity_roles]
                if input.source_entity_roles
                else []
            ),
            target_entity_roles=(
                [strawberry.asdict(v) for v in input.target_entity_roles]
                if input.target_entity_roles
                else []
            ),
            source_reagent_roles=(
                [strawberry.asdict(v) for v in input.source_reagent_roles]
                if input.source_reagent_roles
                else []
            ),
            target_reagent_roles=(
                [strawberry.asdict(v) for v in input.target_reagent_roles]
                if input.target_reagent_roles
                else []
            ),
            variable_definitions=(
                [strawberry.asdict(v) for v in input.variable_definitions]
                if input.variable_definitions
                else []
            ),
            plate_children=(
                [strawberry.asdict(v) for v in input.plate_children]
                if input.plate_children
                else []
            ),
        ),
    )

    age.create_age_protocol_event_kind(protocol_event)
    manager.set_age_sequence(protocol_event, input.sequence, auto_create=input.auto_create_sequence)
    manager.set_position_info(protocol_event, input)

    if input.tags:
        protocol_event.tags.clear()
        for tag in input.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag)
            protocol_event.tags.add(tag_obj)

    return protocol_event


def update_protocol_event_category(
    info: Info, input: UpdateProtocolEventCategoryInput
) -> types.ProtocolEventCategory:
    source_entity_role_names = list(map(lambda v: v.role, input.source_entity_roles)) if input.source_entity_roles else []
    target_entity_role_names = list(map(lambda v: v.role, input.target_entity_roles)) if input.target_entity_roles else []
    source_reagent_role_names = list(map(lambda v: v.role, input.source_reagent_roles)) if input.source_reagent_roles else []
    target_reagent_role_names = list(map(lambda v: v.role, input.target_reagent_roles)) if input.target_reagent_roles else []
    variable_params = list(map(lambda v: v.param, input.variable_definitions)) if input.variable_definitions else []
    
    
    all_roles = source_entity_role_names + target_entity_role_names + source_reagent_role_names + target_reagent_role_names + variable_params
    assert len(all_roles) == len(set(all_roles)), "Roles must be unique" 
    
    
    
    item = models.ProtocolEventCategory.objects.get(id=input.id)

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
    
    
    
    
    if input.source_entity_roles:
        item.source_entity_roles = [
            strawberry.asdict(v) for v in input.source_entity_roles
        ]
        
    if input.target_entity_roles:
        item.target_entity_roles = [
            strawberry.asdict(v) for v in input.target_entity_roles
        ]
        
    if input.source_reagent_roles:
        item.source_reagent_roles = [
            strawberry.asdict(v) for v in input.source_reagent_roles
        ]
        
    if input.target_reagent_roles:
        item.target_reagent_roles = [
            strawberry.asdict(v) for v in input.target_reagent_roles
        ]
        
    if input.plate_children:
        item.plate_children = [
            strawberry.asdict(v) for v in input.plate_children
        ]
        
    if input.variable_definitions:
        item.variable_definitions = [
            strawberry.asdict(v) for v in input.variable_definitions
        ]
        
    manager.set_position_info(item, input)
    
        
    #TODO: Check if we need to kill some events in order to update the source and target entity roles

    item.save()
    
    loaders.protocol_event_category_loader.clear(item.id)
    return item


def delete_protocol_event_category(
    info: Info,
    input: DeleteProtocolEventCategoryInput,
) -> strawberry.ID:
    item = models.ProtocolEventCategory.objects.get(id=input.id)
    item.delete()
    return input.id
