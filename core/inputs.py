import strawberry_django
from core import models, enums, scalars
from typing import List, Optional
from strawberry import ID
import strawberry
import pydantic


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
    category_definition: CategoryDefinitionInput = strawberry.field(
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
    category_definition: CategoryDefinitionInput = strawberry.field(
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


@strawberry.input
class NodeMapping:
    key: str
    node: strawberry.ID
    quantity: float | None = None


@strawberry.input
class VariableMapping:
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


@strawberry.input()
class CategoryInput:
    graph: strawberry.ID = strawberry.field(
        description="The ID of the graph this expression belongs to. If not provided, uses default ontology",
    )
    description: str | None = strawberry.field(
        default=None, description="A detailed description of the expression"
    )
    purl: str | None = strawberry.field(
        default=None, description="Permanent URL identifier for the expression"
    )
    color: list[int] | None = strawberry.field(
        default=None, description="RGBA color values as list of 3 or 4 integers"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="An optional image associated with this expression"
    )
    tags: list[str] | None = strawberry.field(
        default=None, description="A list of tags associated with this expression"
    )
    pin: bool | None = strawberry.field(
        default=None, description="Whether this expression should be pinned or not"
    )


@strawberry.input()
class UpdateCategoryInput:
    description: str | None = strawberry.field(
        default=None, description="A detailed description of the expression"
    )
    purl: str | None = strawberry.field(
        default=None, description="Permanent URL identifier for the expression"
    )
    color: list[int] | None = strawberry.field(
        default=None, description="RGBA color values as list of 3 or 4 integers"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="An optional image associated with this expression"
    )
    tags: list[str] | None = strawberry.field(
        default=None, description="A list of tags associated with this expression"
    )
    pin: bool | None = strawberry.field(
        default=None, description="Whether this expression should be pinned or not"
    )