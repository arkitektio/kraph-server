import strawberry_django
from core import models, enums
from typing import List, Optional
from strawberry import ID
import strawberry


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
    value_kind: enums.MeasurementKind | None = None
    searchable: bool | None = None
    
    
