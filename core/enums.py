from django.db.models import TextChoices
import strawberry
from enum import Enum
import strawberry
from enum import Enum

import strawberry
from enum import Enum


class MeasurementKindChoices(TextChoices):
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
class MetricKind(str, Enum):
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
class ExpressionKind(str, Enum):
    STRUCTURE = "STRUCTURE"
    MEASUREMENT = "MEASUREMENT"
    RELATION = "relation"
    ENTITY = "entity"
    METRIC = "metric"
    RELATION_METRIC = "relation_metric"
    CONCEPT = "concept"


@strawberry.enum
class InstanceKind(str, Enum):
    """Describes how the instance is related to the class.

    I.e. a LOT means that the instance reflects some instances of the class. (Antibody Lot)
    an ENTITY means that the instance is a single instance of the class. (A single mouse)


    """

    LOT = "LOT"
    SAMPLE = "SAMPLE_OF"
    ENTITY = "ENTITY"
    UNKNOWN = "UNKNOWN"


@strawberry.enum
class ViewKind(str, Enum):
    PATH = "PATH"
    PAIRS = "PAIRS"
    TABLE = "TABLE"
    INT_METRIC = "INT_METRIC"
    FLOAT_METRIC = "FLOAT_METRIC"
    NODE_LIST = "NODE_LIST"
    EDGE_LIST = "EDGE_LIST"


@strawberry.enum
class ColumnKind(str, Enum):
    NODE = "NODE"
    VALUE = "VALUE"
    EDGE = "EDGE"


@strawberry.enum
class ParticipantKind(str, Enum):
    """Describes the kind of participant"""

    REAGENT = "REAGENT"
    ENTITY = "ENTITY"


@strawberry.enum
class NodeCategoryKind(str, Enum):
    """Describes the kind of ontology node"""

    ENTITY = "ENTITY"
    STRUCTURE = "STRUCTURE"
    METRIC = "METRIC"
    NATURAL_EVENT = "NATURAL_EVENT"
    PROTOCOL_EVENT = "PROTOCOL_EVENT"
    

@strawberry.enum
class EdgeCategoryKind(str, Enum):
    """Describes the kind of ontology edge"""

    RELATION = "RELATION"
    MEASUREMENT = "MEASUREMENT"
    DESCRIPTION = "DESCRIPTION"
    IN_EVENT = "IN_EVENT"
    OUT_EVENT = "OUT_EVENT"
