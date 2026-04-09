from django.db.models import TextChoices
import strawberry
from enum import Enum


class MetricKindChoices(TextChoices):
    INT = "INT"
    FLOAT = "FLOAT"
    DATETIME = "DATETIME"
    STRING = "STRING"
    CATEGORY = "CATEGORY"
    BOOLEAN = "BOOLEAN"
    THREE_D_VECTOR = "THREE_D_VECTOR"
    TWO_D_VECTOR = "TWO_D_VECTOR"
    ONE_D_VECTOR = "ONE_D_VECTOR"
    FOUR_D_VECTOR = "FOUR_D_VECTOR"
    N_VECTOR = "N_VECTOR"


class ProtocolStepKindChoices(TextChoices):
    """Variety expresses the Type of Representation we are dealing with"""

    PREPERATION = "PREP"
    ADD_REAGENT = "ADD_REAGENT"
    MEASUREMENT = "MEASUREMENT"
    STORAGE = "STORAGE"
    CUSTOM = "CUSTOM"
    UNKNOWN = "UNKNOWN"


@strawberry.enum
class ProtocolStepKind(str, Enum):
    """Variety expresses the Type of Representation we are dealing with"""

    PREPERATION = "PREP"
    ADD_REAGENT = "ADD_REAGENT"
    MEASUREMENT = "MEASUREMENT"
    ANALYSIS = "ANALYSIS"
    STORAGE = "STORAGE"
    CUSTOM = "CUSTOM"
    UNKNOWN = "UNKNOWN"


@strawberry.enum
class ValueKind(str, Enum):
    INT = "INT"
    FLOAT = "FLOAT"
    DATETIME = "DATETIME"
    STRING = "STRING"
    CATEGORY = "CATEGORY"
    BOOLEAN = "BOOLEAN"
    THREE_D_VECTOR = "THREE_D_VECTOR"
    TWO_D_VECTOR = "TWO_D_VECTOR"
    ONE_D_VECTOR = "ONE_D_VECTOR"
    FOUR_D_VECTOR = "FOUR_D_VECTOR"
    N_VECTOR = "N_VECTOR"


@strawberry.enum
class WhereOperator(str, Enum):
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    CONTAINS = "CONTAINS"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"


@strawberry.enum
class ChangeKind(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    IMPORT = "IMPORT"


@strawberry.enum
class OrderDirection(str, Enum):
    ASC = "ASC"
    DESC = "DESC"
