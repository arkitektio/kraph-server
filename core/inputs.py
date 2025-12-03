import strawberry_django
from core import models, enums, scalars
from typing import List, Optional
from strawberry import ID
import strawberry
import pydantic
import datetime
from rekuest_core.inputs.types import PortInput


@strawberry.input
class ContextInput:
    assignation_id: strawberry.ID | None = None
    assignee_id: strawberry.ID | None = None
    template_id: strawberry.ID | None = None
    node_id: strawberry.ID | None = None
    args: scalars.Any | None = None


@strawberry.input
class PlateChildInput:
    id: strawberry.ID | None = None
    type: str | None = None
    text: str | None = None
    children: list["PlateChildInput"] | None = None
    value: str | None = None
    color: str | None = None
    fontSize: str | None = None
    backgroundColor: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None


def child_to_str(child):
    if child.get("children", []) is None:
        return (" ".join([child_to_str(c) for c in child["children"]]),)
    else:
        return child.get("value", child.get("text", "")) or ""


def plate_children_to_str(children):
    return " ".join([child_to_str(c) for c in children])


@strawberry.input
class OptionInput:
    label: str = strawberry.field(description="The label of the option")
    value: scalars.Any = strawberry.field(
        description="The value of the option. This can be a string, number, or boolean",
    )
    description: str | None = strawberry.field(
        default=None,
        description="A detailed description of the option",
    )


@strawberry.input(description="Input for creating a new expression")
class VariableDefinitionInput:
    param: str = strawberry.field(description="The parameter name")
    value_kind: enums.MetricKind = strawberry.field(
        default=None,
        description="The type of metric data this expression represents",
    )
    optional: bool | None = strawberry.field(
        default=False,
        description="Whether this port is optional or not",
    )
    default: scalars.Any | None = strawberry.field(
        default=None,
        description="The default value for this port",
    )
    description: str | None = strawberry.field(
        default=None,
        description="A detailed description of the role",
    )
    label: str | None = strawberry.field(
        default=None,
        description="The label/name of the role",
    )
    options: list[OptionInput] | None = strawberry.field(
        default=None,
        description="A list of options for this port (if only a few values are allowed)",
    )


@strawberry.input(description="Input for defining a property on a node category")
class PropertyDefinitionInput:
    key: str = strawberry.field(description="The property key/name")
    value_kind: enums.MetricKind = strawberry.field(
        description="The type of data this property stores",
    )
    optional: bool | None = strawberry.field(
        default=False,
        description="Whether this property is optional or not",
    )
    default: scalars.Any | None = strawberry.field(
        default=None,
        description="The default value for this property",
    )
    description: str | None = strawberry.field(
        default=None,
        description="A detailed description of the property",
    )
    label: str | None = strawberry.field(
        default=None,
        description="The label/name of the property",
    )
    options: list[OptionInput] | None = strawberry.field(
        default=None,
        description="A list of options for this property (if only a few values are allowed)",
    )
    searchable: bool | None = strawberry.field(default=None, description="WHere or not this is searchable")
    use_as_label: bool | None = strawberry.field(
        default=None,
        description="Whether to use this property as a label when displaying nodes of this category",
    )


@strawberry.input(description="Input for creating a new expression")
class CategoryDefinitionInput:
    category_filters: list[strawberry.ID] | None = strawberry.field(
        default=None,
        description="A list of classes to filter the entities",
    )
    tag_filters: list[str] | None = strawberry.field(
        default=None,
        description="A list of tags to filter the entities by",
    )
    default_use_active: strawberry.ID | None = strawberry.field(
        default=None,
        description="The default ACTIVE reagent category to use for this port if a reagent is not provided",
    )
    default_use_new: strawberry.ID | None = strawberry.field(
        default=None,
        description="The default creation of entity or reagent to use for this port if a reagent is not provided",
    )


@strawberry.input(description="Input for creating a new expression")
class EntityCategoryDefinitionInput:
    category_filters: list[strawberry.ID] | None = strawberry.field(
        default=None,
        description="A list of classes to filter the entities",
    )
    tag_filters: list[str] | None = strawberry.field(
        default=None,
        description="A list of tags to filter the entities by",
    )
    default_use_new: strawberry.ID | None = strawberry.field(
        default=None,
        description="The default creation of entity or reagent to use for this port if a reagent is not provided",
    )


@strawberry.input(description="Input for creating a new expression")
class ReagentCategoryDefinitionInput:
    category_filters: list[strawberry.ID] | None = strawberry.field(
        default=None,
        description="A list of classes to filter the entities",
    )
    tag_filters: list[str] | None = strawberry.field(
        default=None,
        description="A list of tags to filter the entities by",
    )
    default_use_active: strawberry.ID | None = strawberry.field(
        default=None,
        description="The default ACTIVE reagent category to use for this port if a reagent is not provided",
    )
    default_use_new: strawberry.ID | None = strawberry.field(
        default=None,
        description="The default creation of entity or reagent to use for this port if a reagent is not provided",
    )


@strawberry.input(description="Input for creating a new expression")
class StructureCategoryDefinitionInput:
    category_filters: list[strawberry.ID] | None = strawberry.field(
        default=None,
        description="A list of classes to filter the entities",
    )
    identifier_filters: list[scalars.StructureIdentifier] | None = strawberry.field(
        default=None,
        description="A list of StructureIdentifier to filter the entities",
    )
    tag_filters: list[str] | None = strawberry.field(
        default=None,
        description="A list of tags to filter the entities by",
    )
    default_use_active: strawberry.ID | None = strawberry.field(
        default=None,
        description="The default ACTIVE reagent to use for this port if a reagent is not provided",
    )
    default_use_new: strawberry.ID | None = strawberry.field(
        default=None,
        description="The default creation of entity or reagent to use for this port if a reagent is not provided",
    )


@strawberry.input(description="Input for creating a new expression")
class ReagentRoleDefinitionInput:
    role: str = strawberry.field(description="The parameter name")
    needs_quantity: bool | None = strawberry.field(
        default=False,
        description="Whether this port needs a quantity or not",
    )
    variable_amount: bool | None = strawberry.field(
        default=True,
        description="Whether this port allows a variable amount of entities or not",
    )
    optional: bool | None = strawberry.field(
        default=False,
        description="Whether this port is optional or not",
    )
    category_definition: ReagentCategoryDefinitionInput = strawberry.field(
        description="The category definition for this expression",
    )
    description: str | None = strawberry.field(
        default=None,
        description="A detailed description of the role",
    )
    label: str | None = strawberry.field(
        default=None,
        description="The label/name of the role",
    )
    allow_multiple: bool | None = strawberry.field(
        default=False,
        description="Whether this port allows multiple entities or not",
    )
    create_category: strawberry.ID | None = strawberry.field(
        default=None,
        description="The ID of the category to create a new reagent for if it doesn't exist",
    )


@strawberry.input(description="Input for creating a new expression")
class EntityRoleDefinitionInput:
    role: str = strawberry.field(description="The parameter name")
    variable_amount: bool | None = strawberry.field(
        default=True,
        description="Whether this port allows a variable amount of entities or not",
    )
    optional: bool | None = strawberry.field(
        default=False,
        description="Whether this port is optional or not",
    )
    category_definition: EntityCategoryDefinitionInput = strawberry.field(
        description="The category definition for this expression",
    )
    description: str | None = strawberry.field(
        default=None,
        description="A detailed description of the role",
    )
    label: str | None = strawberry.field(
        default=None,
        description="The label/name of the role",
    )
    allow_multiple: bool | None = strawberry.field(
        default=False,
        description="Whether this port allows multiple entities or not",
    )
    create_category: strawberry.ID | None = strawberry.field(
        default=None,
        description="The ID of the category to create an entity for if it doesn't exist",
    )


@strawberry.input
class NodeMapping:
    key: str
    node: strawberry.ID
    quantity: float | None = None


@strawberry.input
class VariableMappingInput:
    key: str
    value: scalars.Any


@strawberry.input()
class Structure:
    identifier: str
    id: strawberry.ID


@strawberry.input()
class AssociateInput:
    selfs: List[strawberry.ID]
    other: strawberry.ID


@strawberry.input()
class DesociateInput:
    selfs: List[strawberry.ID]
    other: strawberry.ID


@strawberry.input()
class ColumnInput:
    name: str
    kind: enums.ColumnKind
    label: str | None = None
    description: str | None = None
    category: strawberry.ID | None = None
    value_kind: enums.MetricKind | None = None
    searchable: bool | None = None
    idfor: list[strawberry.ID] | None = None
    preferhidden: bool | None = None
    identifier: str | None = None


@strawberry.input()
class WithGraphInput:
    graph: strawberry.ID = strawberry.field(
        description="The ID of the graph this expression belongs to. If not provided, uses default ontology",
    )


@strawberry.input()
class DescriptorInput:
    key: str = strawberry.field(description="A world unique key of the descriptor")
    value: str | None = strawberry.field(default=None, description="An optional value for the descriptor")
    description: str | None = strawberry.field(default=None, description="A detailed description of the descriptor")


@strawberry.input()
class CategoryInput:
    description: str | None = strawberry.field(default=None, description="A detailed description of the expression")
    purl: str | None = strawberry.field(default=None, description="Permanent URL identifier for the expression")
    color: list[int] | None = strawberry.field(default=None, description="RGBA color values as list of 3 or 4 integers")
    image: strawberry.ID | None = strawberry.field(default=None, description="An optional image associated with this expression")
    tags: list[str] | None = strawberry.field(default=None, description="A list of tags associated with this expression")
    pin: bool | None = strawberry.field(default=None, description="Whether this expression should be pinned or not")
    sequence: strawberry.ID | None = strawberry.field(
        default=None,
        description="The ID of the sequence this category will get internal_ids from",
    )
    auto_create_sequence: bool | None = strawberry.field(
        default=False,
        description="Whether to create a sequence if it does not exist",
    )
    descriptors: list[DescriptorInput] | None = strawberry.field(
        default=None,
        description="A list of descriptor IDs to associate with this category",
    )


@strawberry.input()
class NodeCategoryInput:
    position_x: float | None = strawberry.field(default=None, description="An optional x position for the ontology node")
    position_y: float | None = strawberry.field(default=None, description="An optional y position for the ontology node")
    height: float | None = strawberry.field(default=None, description="An optional height for the ontology node")
    width: float | None = strawberry.field(default=None, description="An optional width for the ontology node")
    color: list[int] | None = strawberry.field(default=None, description="An optional RGBA color for the ontology node")
    property_definitions: list[PropertyDefinitionInput] | None = strawberry.field(
        default=None,
        description="A list of property definitions for this node category",
    )


@strawberry.input()
class UpdateCategoryInput:
    description: str | None = strawberry.field(default=None, description="A detailed description of the expression")
    purl: str | None = strawberry.field(default=None, description="Permanent URL identifier for the expression")
    color: list[int] | None = strawberry.field(default=None, description="RGBA color values as list of 3 or 4 integers")
    image: strawberry.ID | None = strawberry.field(default=None, description="An optional image associated with this expression")
    tags: list[str] | None = strawberry.field(default=None, description="A list of tags associated with this expression")
    pin: bool | None = strawberry.field(default=None, description="Whether this expression should be pinned or not")


@strawberry.input
class GraphQueryFilters:
    search: Optional[str] = None
    valid_from: Optional[datetime.datetime] = None
    valid_to: Optional[datetime.datetime] = None


@strawberry.input
class CategoryNodesFilter:
    search: Optional[str] = None
    valid_from: Optional[datetime.datetime] = None
    valid_to: Optional[datetime.datetime] = None


@strawberry.input
class GraphQueryPagination:
    limit: Optional[int] = None
    offset: Optional[int] = None


@strawberry.input
class GraphQueryOrder:
    field: Optional[str] = None
    direction: Optional[str] = None


@strawberry.input
class NodeQueryFilters:
    search: Optional[str] = None
    valid_from: Optional[datetime.datetime] = None
    valid_to: Optional[datetime.datetime] = None


@strawberry.input
class NodeQueryPagination:
    limit: Optional[int] = None
    offset: Optional[int] = None


@strawberry.input
class NodeQueryOrder:
    field: Optional[str] = None
    direction: Optional[str] = None


@strawberry.input(description="Input for creating a new expression")
class EntityCategorySchemaInput(CategoryInput, NodeCategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")


@strawberry.input(description="Input for creating a new expression")
class EntityCategoryInput(EntityCategorySchemaInput, WithGraphInput):
    label: str = strawberry.field(description="The label/name of the expression")


@strawberry.input(description="Input for creating a new expression")
class MeasurementCategorySchemaInput(CategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    structure_definition: StructureCategoryDefinitionInput = strawberry.field(
        default=None,
        description="The source definition for this expression",
    )
    entity_definition: EntityCategoryDefinitionInput = strawberry.field(
        default=None,
        description="The target definition for this expression",
    )


@strawberry.input(description="Input for creating a new expression")
class MeasurementCategoryInput(MeasurementCategorySchemaInput, WithGraphInput):
    pass


@strawberry.input(description="Input for creating a new natural event category")
class NaturalEventCategorySchemaInput(CategoryInput, NodeCategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    source_entity_roles: list[EntityRoleDefinitionInput] | None = strawberry.field(
        default=None,
        description="The source definitions for this expression",
    )
    target_entity_roles: list[EntityRoleDefinitionInput] | None = strawberry.field(
        default=None,
        description="The target definitions for this expression",
    )


@strawberry.input(description="Input for creating a new protocol event category")
class ProtocolEventCategorySchemaInput(CategoryInput, NodeCategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    source_entity_roles: list[EntityRoleDefinitionInput] | None = strawberry.field(
        default=None,
        description="The source entity roles for this expression",
    )
    target_entity_roles: list[EntityRoleDefinitionInput] | None = strawberry.field(
        default=None,
        description="The target entity roles for this expression",
    )
    source_reagent_roles: list[ReagentRoleDefinitionInput] | None = strawberry.field(
        default=None,
        description="The source reagent roles for this expression",
    )
    target_reagent_roles: list[ReagentRoleDefinitionInput] | None = strawberry.field(
        default=None,
        description="The target reagent roles for this expression",
    )
    variable_definitions: list[VariableDefinitionInput] | None = strawberry.field(
        default=None,
        description="The variable definitions for this expression",
    )


@strawberry.input(description="Input for creating a new protocol event category")
class SchemaDefinitionInput:
    tags: list[str] | None = strawberry.field(default=None, description="A list of tags associated with this expression")
    labels: list[str] | None = strawberry.field(default=None, description="A list of labels associated with this expression")


@strawberry.input(description="Input for creating a new protocol event category")
class RelationCategorySchemaInput(CategoryInput):
    label: str = strawberry.field(description="The label/name of the expression")
    source_definition: SchemaDefinitionInput = strawberry.field(
        description="The source definition for this expression",
    )
    target_definition: SchemaDefinitionInput = strawberry.field(
        description="The target definition for this expression",
    )
    property_definitions: list[PropertyDefinitionInput] | None = strawberry.field(
        default=None,
        description="A list of property definitions for this relation category",
    )


@strawberry.input(description="An ontology/graph")
class SchemaInput:
    entity_schemas: list[EntityCategorySchemaInput] = strawberry.field(description="List of entity categories in the ontology")
    measurement_schemas: list[MeasurementCategorySchemaInput] = strawberry.field(description="List of measurement categories in the ontology")
    natural_event_schemas: list[NaturalEventCategorySchemaInput] | None = strawberry.field(default=None, description="List of natural event categories in the ontology")
    protocol_event_schemas: list[ProtocolEventCategorySchemaInput] | None = strawberry.field(default=None, description="List of protocol event categories in the ontology")
    relation_schemas: list[RelationCategorySchemaInput] | None = strawberry.field(default=None, description="List of relation categories in the ontology")
