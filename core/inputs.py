import strawberry_django
from core import models
from typing import List, Optional
from strawberry import ID
import strawberry


@strawberry.input()
class AssociateInput:
    selfs: List[strawberry.ID]
    other: strawberry.ID

@strawberry.input()
class DesociateInput:
    selfs: List[strawberry.ID]
    other: strawberry.ID
