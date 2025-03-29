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
class VariableDefinition:
    param: str = strawberry.field(description="The parameter name")
    variable_kind: enums.MetricKind = strawberry.field(
        default=None,
        description="The type of metric data this expression represents",
    )
    optional: bool = strawberry.field(
        default=False,
        description="Whether this port is optional or not",
    )
    


@strawberry.input(description="Input for creating a new expression")
class ParticipantDefinition:
    kind: enums.ParticipantKind = strawberry.field(
        default=None,
        description="The type of participant this expression represents",
    )
    param: str = strawberry.field(description="The parameter name")
    tag_filters: list[str] = strawberry.field(
        default=None,
        description="A list of tags to filter the entities by",
    ) 
    category_filters: list[strawberry.ID] = strawberry.field(
        default=None,
        description="A list of classes to filter the entities",
    )
    needs_quantity: bool = strawberry.field(
        default=False,
        description="Whether this port needs a quantity or not",
    )
    default_use_active: strawberry.ID | None = strawberry.field(
        default=None,
        description="The default ACTIVE reagent to use for this port if a reagent is not provided",
    )
    default_use_new: strawberry.ID | None = strawberry.field(
        default=None,
        description="The default creation of entity or reagent to use for this port if a reagent is not provided",
    )
    optional: bool = strawberry.field(
        default=False,
        description="Whether this port is optional or not",
    )
    variable_amount: bool = strawberry.field(
        default=False,
        description="Whether this port allows a variable amount of entities or not",
    )
    

@strawberry.input
class InputMapping:
    key: str
    node: strawberry.ID


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
    expression: strawberry.ID | None = None
    value_kind: enums.MetricKind | None = None
    searchable: bool | None = None
    
    

@strawberry.input()
class CategoryInput:
    graph: strawberry.ID | None = strawberry.field(
        default=None,
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