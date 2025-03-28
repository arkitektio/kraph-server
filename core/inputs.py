import strawberry_django
from core import models, enums
from typing import List, Optional
from strawberry import ID
import strawberry
import pydantic

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